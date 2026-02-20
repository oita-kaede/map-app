import streamlit as st
import json
import numpy as np
from PIL import Image
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- 🛠️ 設定：各管轄のスタート地点ID ---
DRIVE_IDS = {
    "工務店管轄": "1nqci7jC-FL4PUGuuSJ-FzMB7VwLLjY5w", # 「営業担当者」
    "不動産管轄": "1I8DmZL_B2fi-IZiDBSivo71ghBA-PWA7"  # 「★分譲決定物件」
}

st.set_page_config(page_title="建築現場マップ作成ツール", layout="wide")

# --- 🔐 Google認証 ---
def get_flow():
    client_config = json.loads(st.secrets["GCP_OAUTH_JSON"])
    flow = Flow.from_client_config(
        client_config,
        scopes=['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive.metadata.readonly'],
        redirect_uri=client_config["web"]["redirect_uris"][0]
    )
    return flow

if "credentials" not in st.session_state:
    st.title("🔒 ログイン")
    flow = get_flow()
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    st.info("会社のアカウントでログインしてください。")
    st.link_button("Googleでログイン", auth_url)
    if "code" in st.query_params:
        flow.fetch_token(code=st.query_params["code"])
        st.session_state.credentials = flow.credentials
        st.rerun()
    st.stop()

drive_service = build('drive', 'v3', credentials=st.session_state.credentials)

# --- 📁 フォルダ操作関数 ---
def list_subfolders(parent_id, root_id):
    """指定したフォルダ内のフォルダ一覧を取得"""
    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    response = drive_service.files().list(
        q=query, spaces='drive', corpora='drive', driveId=root_id,
        includeItemsFromAllDrives=True, supportsAllDrives=True, fields='files(id, name)'
    ).execute()
    return sorted(response.get('files', []), key=lambda x: x['name'])

def find_map_folder_auto(parent_id, root_id):
    """「現場までの地図」という名前のフォルダを自動で探す"""
    query = f"name contains '現場までの地図' and mimeType = 'application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed = false"
    response = drive_service.files().list(
        q=query, spaces='drive', corpora='drive', driveId=root_id,
        includeItemsFromAllDrives=True, supportsAllDrives=True, fields='files(id, name)'
    ).execute()
    files = response.get('files', [])
    return files[0] if files else None

# --- 🏠 アプリ本体 ---
st.title("📍 建築現場マップ作成ツール")

# 1. 管轄の選択
st.subheader("ステップ1：管轄とお客様フォルダを選択")
jurisdiction = st.radio("管轄を選択してください", list(DRIVE_IDS.keys()), horizontal=True)
ROOT_ID = DRIVE_IDS[jurisdiction]

# 2. 手動ナビゲート（お客様フォルダまで）
col1, col2 = st.columns(2)

with col1:
    if jurisdiction == "工務店管轄":
        st.write("📁 **営業担当者を選択**")
        staff_list = list_subfolders(ROOT_ID, ROOT_ID)
        selected_staff = st.selectbox("担当者フォルダを選んでください", staff_list, format_func=lambda x: x['name'], key="staff_sel")
        current_parent_id = selected_staff['id'] if selected_staff else ROOT_ID
    else:
        current_parent_id = ROOT_ID

with col2:
    st.write("📁 **お客様 / 現場フォルダを選択**")
    customer_list = list_subfolders(current_parent_id, ROOT_ID)
    selected_customer = st.selectbox("お客様フォルダを選んでください", customer_list, format_func=lambda x: x['name'], key="cust_sel")

st.write("---")

# 3. 画像アップロードと自動保存
st.subheader("ステップ2：画像のアップロードと保存")
uploaded_file = st.file_uploader("地図の画像をアップロード", type=['png', 'jpg', 'jpeg'])

if uploaded_file and selected_customer:
    img = Image.open(uploaded_file)
    st.image(img, use_container_width=True)
    
    # 自動で「現場までの地図」フォルダを探す
    with st.spinner("「現場までの地図」フォルダを自動スキャン中..."):
        target_folder = find_map_folder_auto(selected_customer['id'], ROOT_ID)
    
    if target_folder:
        st.success(f"📍 自動検出成功：{selected_customer['name']} ＞ {target_folder['name']}")
        if st.button("🚀 このフォルダに保存する"):
            with st.spinner("ドライブに保存中..."):
                try:
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    buf.seek(0)
                    file_name = f"{selected_customer['name']}_現場地図.png"
                    file_metadata = {'name': file_name, 'parents': [target_folder['id']]}
                    media = MediaIoBaseUpload(buf, mimetype='image/png')
                    drive_service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()
                    st.success(f"✅ 「{target_folder['name']}」に保存しました！")
                    st.balloons()
                except Exception as e:
                    st.error(f"保存エラー: {e}")
    else:
        st.error(f"❌ 「{selected_customer['name']}」の中に『現場までの地図』フォルダが見つかりません。")
        st.info("ドライブ上でフォルダを作成してから、アプリを再読み込みしてください。")

elif not selected_customer:
    st.info("👆 まずはお客様のフォルダを選択してください。")
