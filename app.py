import streamlit as st
import json
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- 🛠️ 設定：各管轄のスタート地点ID ---
DRIVE_IDS = {
    "工務店管轄": "1nqci7jC-FL4PUGuuSJ-FzMB7VwLLjY5w",
    "不動産管轄": "1I8DmZL_B2fi-IZiDBSivo71ghBA-PWA7"
}

st.set_page_config(page_title="建築現場マップ作成ツール", layout="wide", page_icon="📍")

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
    st.title("🔒 Googleログインが必要です")
    flow = get_flow()
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    st.info("会社のアカウントでログインして、Googleドライブへの保存を許可してください。")
    st.link_button("Googleでログイン", auth_url)
    
    if "code" in st.query_params:
        try:
            flow.fetch_token(code=st.query_params["code"])
            st.session_state.credentials = flow.credentials
            st.query_params.clear()
            st.rerun()
        except Exception:
            st.query_params.clear()
            st.rerun()
    st.stop()

drive_service = build('drive', 'v3', credentials=st.session_state.credentials)

# --- 📁 フォルダ操作関数 ---
def list_subfolders(parent_id):
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        response = drive_service.files().list(
            q=query, spaces='drive', corpora='allDrives',
            includeItemsFromAllDrives=True, supportsAllDrives=True, fields='files(id, name)'
        ).execute()
        return sorted(response.get('files', []), key=lambda x: x['name'])
    except Exception as e:
        return []

def find_map_folder_auto(parent_id):
    try:
        query = f"name contains '現場までの地図' and mimeType = 'application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed = false"
        response = drive_service.files().list(
            q=query, spaces='drive', corpora='allDrives',
            includeItemsFromAllDrives=True, supportsAllDrives=True, fields='files(id, name)'
        ).execute()
        files = response.get('files', [])
        return files[0] if files else None
    except Exception as e:
        return None

# --- 🤖 1. 赤いピンの先端を探す ---
def get_pin_tip_position(pil_image):
    img_array = np.array(pil_image)
    hsv = cv2.cvtColor(img_array, cv2.COLOR_RGB2HSV)
    lower_red1 = np.array([0, 70, 50])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([170, 70, 50])
    upper_red2 = np.array([180, 255, 255])
    mask = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        bottom = largest[largest[:, :, 1].argmax()][0]
        return int(bottom[0]), int(bottom[1])
    return pil_image.width // 2, pil_image.height // 2

# --- 🤖 2. 建物を避ける計算 ---
def calculate_path_score(image, points):
    gray_img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    score = 0
    sample_count = 0
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i+1]
        dist = int(np.hypot(p2[0]-p1[0], p2[1]-p1[1]))
        if dist == 0: continue
        for t in np.linspace(0, 1, num=dist):
            x = int(p1[0] * (1-t) + p2[0] * t)
            y = int(p1[1] * (1-t) + p2[1] * t)
            if 0 <= y < gray_img.shape[0] and 0 <= x < gray_img.shape[1]:
                brightness = gray_img[y, x]
                # 「薄いグレー（明るさ215〜250）」は建物なので超避ける
                if 215 < brightness < 250:
                    score += 1000
                else:
                    score += 1
                sample_count += 1
    if sample_count == 0: return 9999999
    return score / sample_count

# --- 🎨 3. 線と文字を描く ---
def draw_label(image, target_x, target_y, label_text, mode):
    draw = ImageDraw.Draw(image)
    pin_x, pin_y = get_pin_tip_position(image)
    
    font_size = 40
    padding_x, padding_y = 15, 10
    try:
        font = ImageFont.truetype("ipaexg.ttf", font_size)
    except:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label_text, font=font)
    w = (bbox[2] - bbox[0]) + padding_x * 2
    h = (bbox[3] - bbox[1]) + padding_y * 2
    
    center_x, center_y = target_x, target_y
    rect_left = target_x - (w / 2)
    rect_top = target_y - (h / 2)
    rect_right = rect_left + w
    rect_bottom = rect_top + h

    path_straight = [(center_x, center_y), (pin_x, pin_y)]
    path_horz = [(center_x, center_y), (pin_x, center_y), (pin_x, pin_y)]
    path_vert = [(center_x, center_y), (center_x, pin_y), (pin_x, pin_y)]
    best_points = path_straight

    if mode == "自動（建物回避）":
        scores = {
            '直線': calculate_path_score(image, path_straight),
            '横ルート': calculate_path_score(image, path_horz),
            '縦ルート': calculate_path_score(image, path_vert)
        }
        best_route = min(scores, key=scores.get)
        if best_route == '直線': best_points = path_straight
        elif best_route == '横ルート': best_points = path_horz
        else: best_points = path_vert
    elif mode == "直線固定": best_points = path_straight
    elif mode == "カギ型（横優先）": best_points = path_horz
    elif mode == "カギ型（縦優先）": best_points = path_vert

    # 線を描く（赤色・太さ3）
    for i in range(len(best_points) - 1):
        draw.line([best_points[i], best_points[i+1]], fill="red", width=3)
    
    # 白い箱を描く（不透明）
    draw.rectangle((rect_left, rect_top, rect_right, rect_bottom), fill="white", outline="red", width=3)
    
    # 文字を描く
    text_x = rect_left + padding_x
    text_y = rect_top + padding_y - bbox[1]
    draw.text((text_x, text_y), label_text, font=font, fill="black")
    
    return image

# --- 🏠 アプリ画面の構成 ---
st.title("📍 建築現場マップ作成ツール")
st.markdown("道路の上など、**文字を置きたい場所をクリック**してください。AIが**薄いグレー（建物）**を避けて線を引きます。")

# ＝＝＝ サイドバー（設定エリア） ＝＝＝
st.sidebar.header("📁 1. 保存先の設定")
jurisdiction = st.sidebar.radio("管轄を選択", list(DRIVE_IDS.keys()))
ROOT_ID = DRIVE_IDS[jurisdiction]

if jurisdiction == "工務店管轄":
    staff_list = list_subfolders(ROOT_ID)
    selected_staff = st.sidebar.selectbox("営業担当者を選択", staff_list, format_func=lambda x: x['name']) if staff_list else None
    current_parent_id = selected_staff['id'] if selected_staff else ROOT_ID
else:
    current_parent_id = ROOT_ID

customer_list = list_subfolders(current_parent_id) if current_parent_id else []
selected_customer = st.sidebar.selectbox("お客様 / 現場名を選択", customer_list, format_func=lambda x: x['name']) if customer_list else None

st.sidebar.write("---")
st.sidebar.header("✏️ 2. 地図の設定")
label_text = st.sidebar.text_input("吹き出しの文字", "建築現場")
line_mode = st.sidebar.selectbox("線の引き方", ("自動（建物回避）", "直線固定", "カギ型（横優先）", "カギ型（縦優先）"))

st.sidebar.write("---")
if st.sidebar.button("🔄 ログイン状態をリセットする"):
    if "credentials" in st.session_state:
        del st.session_state.credentials
    st.rerun()

# ＝＝＝ メイン画面（地図作成エリア） ＝＝＝
st.subheader("🎨 3. 地図の作成")
uploaded_file = st.file_uploader("画像をアップロード", type=["png", "jpg", "jpeg"])

if uploaded_file and selected_customer:
    image = Image.open(uploaded_file).convert("RGB")
    
    # 画面幅に合わせてリサイズ（クリック座標を正しく取るため）
    base_width = 700
    w_percent = (base_width / float(image.size[0]))
    h_size = int((float(image.size[1]) * float(w_percent)))
    resized_image = image.resize((base_width, h_size), Image.Resampling.LANCZOS)

    st.info("👇 **画像の上をクリックして場所を指定してください**")
    
    # クリック検知パーツ
    coords = streamlit_image_coordinates(resized_image, key="click")

    if coords:
        target_x, target_y = coords['x'], coords['y']
        
        # 画像を作成
        result_image = draw_label(resized_image.copy(), target_x, target_y, label_text, line_mode)
        
        # 表示
        st.image(result_image)

        # ＝＝＝ Googleドライブへ保存 ＆ ダウンロードエリア ＝＝＝
        st.write("---")
        st.subheader("🚀 4. 完成した地図の保存")
        
        # ボタンを横並びに配置
        col1, col2 = st.columns(2)
        
        # [手動ダウンロード機能]
        with col1:
            buf = io.BytesIO()
            result_image.save(buf, format="PNG")
            st.download_button("📥 パソコンにダウンロード", buf.getvalue(), "map_final.png", "image/png")
            
        # [Googleドライブ自動保存機能]
        with col2:
            with st.spinner("「現場までの地図」フォルダを確認中..."):
                target_folder = find_map_folder_auto(selected_customer['id'])
            
            if target_folder:
                st.success(f"保存先：{selected_customer['name']} ＞ {target_folder['name']}")
                
                if st.button("☁️ 「挨拶チラシ地図」としてドライブに保存"):
                    with st.spinner("アップロード中..."):
                        try:
                            # 巻き戻し（getvalue()を使わずに再度最初から読み込ませる）
                            buf.seek(0)
                            
                            file_name = "挨拶チラシ地図.png"
                            file_metadata = {'name': file_name, 'parents': [target_folder['id']]}
                            media = MediaIoBaseUpload(buf, mimetype='image/png')
                            drive_service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()
                            
                            st.success(f"✅ 「{target_folder['name']}」フォルダに保存しました！")
                            st.balloons()
                        except Exception as e:
                            st.error(f"保存エラー: {e}")
            else:
                st.error(f"❌ 「現場までの地図」フォルダが見つかりません。")
    else:
        st.warning("地図の上をクリックして、文字の配置場所を決めてください。")

elif not uploaded_file:
    st.info("👆 まずは地図のスクショをアップロードしてください。")
elif not selected_customer:
    st.warning("👈 左側のメニューでお客様名（現場名）を選んでください。")
