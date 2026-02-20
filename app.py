import streamlit as st
import json
import numpy as np
import cv2
from PIL import Image
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- 🛠️ 設定：各管轄のスタート地点ID ---
DRIVE_IDS = {
    "工務店管轄": "1nqci7jC-FL4PUGuuSJ-FzMB7VwLLjY5w", # 「営業担当者」フォルダ
    "不動産管轄": "1I8DmZL_B2fi-IZiDBSivo71ghBA-PWA7"  # 「★分譲決定物件」フォルダ
}

st.set_page_config(page_title="建築現場マップ作成ツール", layout="wide")

# --- 🔐 Google認証 ---
def get_flow():
    # Secretsから鍵を読み込む
    client_config = json.loads(st.secrets["GCP_OAUTH_JSON"])
    flow = Flow.from_client_config(
        client_config,
        scopes=['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive.metadata.readonly'],
        redirect_uri=client_config["web"]["redirect_uris"][0]
    )
    return flow

if "credentials" not in st.session_state:
    st.title("🔒 Googleログインが必要です")
    flow = get_flow()
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    st.info("会社のアカウントでログインして、Googleドライブへの保存を許可してください。")
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

# 1. サイドバーで保存先を「手動」でたどる
st.sidebar.header("📋 1. 保存先の設定")
jurisdiction = st.sidebar.radio("管轄を選択", list(DRIVE_IDS.keys())) #
ROOT_ID = DRIVE_IDS[jurisdiction]

# 担当者選択（工務店のみ）
if jurisdiction == "工務店管轄":
    staff_list = list_subfolders(ROOT_ID, ROOT_ID)
    selected_staff = st.sidebar.selectbox("営業担当者を選択", staff_list, format_func=lambda x: x['name'])
    current_parent_id = selected_staff['id'] if selected_staff else ROOT_ID
else:
    current_parent_id = ROOT_ID

# お客様・現場フォルダ選択
customer_list = list_subfolders(current_parent_id, ROOT_ID)
selected_customer = st.sidebar.selectbox("お客様 / 現場名を選択", customer_list, format_func=lambda x: x['name'])

st.write("---")

# 2. 地図の作成
st.subheader("🎨 2. 地図の作成")
uploaded_file = st.file_uploader("現場のスクショをアップロードしてください", type=['png', 'jpg', 'jpeg'])

if uploaded_file and selected_customer:
    # 画像の読み込み
    image = Image.open(uploaded_file)
    st.image(image, caption=f"作成中の地図: {selected_customer['name']}", use_container_width=True)

    # 3. Googleドライブへ保存（現場までの地図フォルダへ自動潜入）
    st.write("---")
    st.subheader("🚀 3. Googleドライブへ保存")
    
    with st.spinner("「現場までの地図」フォルダを確認中..."):
        target_folder = find_map_folder_auto(selected_customer['id'], ROOT_ID) #
    
    if target_folder:
        st.success(f"保存先：{selected_customer['name']} ＞ {target_folder['name']}")
        
        if st.button("この地図を「挨拶チラシ地図」として保存"):
            with st.spinner("アップロード中..."):
                try:
                    # PIL画像をバイナリに変換
                    buf = io.BytesIO()
                    image.save(buf, format="PNG")
                    buf.seek(0)
                    
                    # ✨ ファイル名を指定通りに修正
                    file_name = "挨拶チラシ地図.png"
                    
                    file_metadata = {'name': file_name, 'parents': [target_folder['id']]}
                    media = MediaIoBaseUpload(buf, mimetype='image/png')
                    drive_service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()
                    
                    st.success(f"✅ 「{target_folder['name']}」フォルダに「{file_name}」を保存しました！")
                    st.balloons()
                except Exception as e:
                    st.error(f"保存エラー: {e}")
    else:
        st.error(f"❌ {selected_customer['name']} の中に「現場までの地図」フォルダが見つかりません。")

elif not uploaded_file:
    st.info("👆 画像をアップロードしてください。")
elif not selected_customer:
    st.warning("👈 左側のメニューでお客様名（現場名）を選んでください。")
