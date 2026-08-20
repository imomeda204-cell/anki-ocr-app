import os
import json
import random
import tempfile
import pandas as pd
from PIL import Image
import streamlit as st
from google import genai
from google.genai import types
import genanki

# ----------------- ページ基本設定 -----------------
st.set_page_config(page_title="Anki Note OCR", page_icon="📱", layout="centered")

st.title("📱 ノートOCR ➔ Anki")

# ----------------- 設定管理 -----------------
CONFIG_FILE = "anki_config.json"

DEFAULT_CONFIG = {
    "note_types": {
        "HSK": ["拼音", "生词", "意思", "例句", "例句翻译-日语"],
        "IELTS": ["Word", "意味", "類義語", "例文", "Note"],
        "IELTS writing": ["Word", "意味", "例文", "Note"],
        "基本": ["表面", "裏面"]
    },
    "decks": [
        "HSK::HSK4",
        "HSK::HSK5",
        "HSK::HSK3,4-1",
        "Weibo中国語",
        "汉语口语123",
        "IELTS3500",
        "IELTS writing",
        "words for paper"
    ]
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

config = load_config()

# ----------------- サイドバー（設定UI） -----------------
st.sidebar.header("⚙️ 設定")

# 1. ノートタイプ選択
note_type_options = list(config["note_types"].keys()) + ["➕ 新規ノートタイプ作成..."]
selected_note_type = st.sidebar.selectbox("📝 ノートタイプを選択", note_type_options)

if selected_note_type == "➕ 新規ノートタイプ作成...":
    new_type_name = st.sidebar.text_input("新規ノートタイプ名", placeholder="例: 専門用語")
    fields_input = st.sidebar.text_input("フィールド名 (カンマ区切り)", value="Word, Meaning, Example")
    if st.sidebar.button("💾 ノートタイプを保存", type="primary"):
        if new_type_name.strip() and fields_input.strip():
            new_fields = [f.strip() for f in fields_input.split(",") if f.strip()]
            config["note_types"][new_type_name.strip()] = new_fields
            save_config(config)
            st.sidebar.success(f"『{new_type_name}』を保存しました！")
            st.rerun()
else:
    current_fields = config["note_types"][selected_note_type]
    fields_input = st.sidebar.text_input("フィールド名 (カンマ区切り)", value=", ".join(current_fields))
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("🔄 フィールド更新"):
            updated_fields = [f.strip() for f in fields_input.split(",") if f.strip()]
            config["note_types"][selected_note_type] = updated_fields
            save_config(config)
            st.sidebar.success("更新しました！")
            st.rerun()
    with col2:
        if selected_note_type not in DEFAULT_CONFIG["note_types"]:
            if st.button("🗑️ タイプ削除"):
                del config["note_types"][selected_note_type]
                save_config(config)
                st.sidebar.warning("削除しました。")
                st.rerun()

fields = [f.strip() for f in fields_input.split(",") if f.strip()]
st.sidebar.markdown(f"**抽出項目:** `{', '.join(fields)}`")

st.sidebar.markdown("---")

# 2. 登録先デッキ選択
deck_options = config["decks"] + ["➕ 新しいデッキ名を手入力..."]
selected_deck_choice = st.sidebar.selectbox("📂 登録先デッキを選択", deck_options)

if selected_deck_choice == "➕ 新しいデッキ名を手入力...":
    deck_name = st.sidebar.text_input("デッキ名を入力", placeholder="例: HSK::HSK6")
    if st.sidebar.button("➕ このデッキをリストに追加保存"):
        if deck_name.strip() and deck_name.strip() not in config["decks"]:
            config["decks"].append(deck_name.strip())
            save_config(config)
            st.sidebar.success(f"『{deck_name}』をリストに追加しました！")
            st.rerun()
else:
    deck_name = selected_deck_choice

# ----------------- APIキー設定 -----------------
api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")

# ----------------- メイン画面（画像アップロード & 解析） -----------------
uploaded_files = st.file_uploader(
    "📸 写真やスクショを選択（複数枚可）", 
    type=["png", "jpg", "jpeg", "webp"], 
    accept_multiple_files=True
)

if uploaded_files:
    st.info(f"合計 {len(uploaded_files)} 枚の画像が選択されています。")

if st.button("✨ まとめてAI解析開始", type="primary", disabled=not (uploaded_files and api_key and fields)):
    with st.spinner("AIが画像から単語を抽出中..."):
        try:
            client = genai.Client(api_key=api_key)
            pil_images = []
            for file in uploaded_files:
                img = Image.open(file)
                img.thumbnail((2048, 2048))
                pil_images.append(img)

            fields_str = ", ".join([f'"{f}"' for f in fields])
            prompt = f"""
            あなたは語学学習ノート・スクショからデータを読み取る専門AIです。
            添付されたすべての画像（手書きノート、電子書籍、アプリのスクショ等）から学習項目を抽出し、
            指定されたAnkiカードのフィールド名にマッピングして単一のJSON配列でまとめて出力してください。

            【対象フィールド名一覧】
            [{fields_str}]

            【ルール】
            1. 各データ項目は、必ず上記のフィールド名（[{fields_str}]）をキーとするJSONオブジェクトにしてください。
            2. 画像内の言語（英語、中国語等）を自動判別し、適切な内容を格納してください。
               - 中国語の場合、漢字は簡字体、ピンインは声調記号付きにしてください。
            3. ノート上で省略されている項目がある場合、学習に適した自然な内容をAIで補完してください。
            4. 出力はMarkdownバッククォートなしの純粋なJSON配列のみにしてください。
            """

            contents = [prompt] + pil_images
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

            extracted_data = json.loads(response.text)
            st.session_state["extracted_df"] = pd.DataFrame(extracted_data)
            st.success(f"🎉 {len(extracted_data)} 件の学習項目を抽出しました！")

        except Exception as e:
            st.error(f"解析エラー: {e}")

# ----------------- プレビュー・直接編集 & APKG生成 -----------------
if "extracted_df" in st.session_state:
    st.subheader("📝 抽出結果プレビュー（表内で直接編集可能）")
    
    edited_df = st.data_editor(st.session_state["extracted_df"], num_rows="dynamic", use_container_width=True)

    # genanki を使って .apkg パッケージをメモリ/一時ファイル上で生成
    def generate_apkg(df, target_deck, field_names):
        model_id = abs(hash(target_deck + "".join(field_names))) % (10**9)
        deck_id = abs(hash(target_deck)) % (10**9)

        # 表面と裏面のテンプレート構築
        front_template = f"<h2>{{{{{field_names[0]}}}}}</h2>"
        back_template = f"{{{{FrontSide}}}}<hr id=answer>"
        for f in field_names[1:]:
            back_template += f"<p><b>{f}:</b> {{{{{f}}}}}</p>"

        anki_model = genanki.Model(
            model_id,
            f"{target_deck} Model",
            fields=[{'name': f} for f in field_names],
            templates=[
                {
                    'name': 'Card 1',
                    'qfmt': front_template,
                    'afmt': back_template,
                },
            ],
            css=".card { font-family: -apple-system, sans-serif; font-size: 20px; text-align: center; color: black; background-color: white; }"
        )

        anki_deck = genanki.Deck(deck_id, target_deck)

        for _, row in df.iterrows():
            row_fields = [str(row.get(f, "") if pd.notna(row.get(f, "")) else "") for f in field_names]
            note = genanki.Note(
                model=anki_model,
                fields=row_fields
            )
            anki_deck.add_note(note)

        package = genanki.Package(anki_deck)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".apkg") as tmp:
            package.write_to_file(tmp.name)
            with open(tmp.name, "rb") as f:
                data = f.read()
        os.remove(tmp.name)
        return data

    apkg_bytes = generate_apkg(edited_df, deck_name, fields)

    st.download_button(
        label=f"📦 『{deck_name}』のAnkiパッケージ (.apkg) をダウンロード",
        data=apkg_bytes,
        file_name=f"{deck_name.replace('::', '_')}.apkg",
        mime="application/octet-stream",
        type="primary"
    )

    st.markdown(f"""
    ---
    **📱 スマホでのAnki取り込み手順:**
    1. 上の **「.apkg をダウンロード」** ボタンをタップ
    2. Safariのダウンロード完了アイコン（または「ファイル」アプリのダウンロード項目）から、ダウンロードした **`.apkg` ファイルをタップ**
    3. **AnkiMobile が自動起動**し、デッキ **`{deck_name}`** に即座にカードが取り込まれます！
    """)
