import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import cv2
import numpy as np
from streamlit_image_coordinates import streamlit_image_coordinates

# --- 1. 赤いピンの先端を自動で探す機能 ---
def get_pin_tip_position(pil_image):
    img_array = np.array(pil_image)
    hsv = cv2.cvtColor(img_array, cv2.COLOR_RGB2HSV)

    # 赤色の定義（ピンの色）
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
    # 見つからない場合は真ん中
    return pil_image.width // 2, pil_image.height // 2

# --- 2. 建物を避ける計算機能 ---
def calculate_path_score(image, points):
    # 画像をグレー変換（0=黒 〜 255=白）
    gray_img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    
    score = 0
    sample_count = 0
    
    # ルート上の色を調べる
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
                
                # ★ここが重要設定★
                # 「薄いグレー（明るさ215〜250）」は建物なので超避ける（+1000点）
                # 「白（255）」や「濃いグレー（道路）」は通ってOK（+1点）
                if 215 < brightness < 250:
                    score += 1000 
                else:
                    score += 1
                
                sample_count += 1
                
    if sample_count == 0: return 9999999
    return score / sample_count

# --- 3. 描画機能 ---
def draw_label(image, target_x, target_y, label_text, mode):
    draw = ImageDraw.Draw(image)
    pin_x, pin_y = get_pin_tip_position(image)

    # フォント設定
    font_size = 40
    padding_x, padding_y = 15, 10
    try:
        font = ImageFont.truetype("ipaexg.ttf", font_size)
    except:
        font = ImageFont.load_default()

    # 文字サイズ計算
    bbox = draw.textbbox((0, 0), label_text, font=font)
    w = (bbox[2] - bbox[0]) + padding_x * 2
    h = (bbox[3] - bbox[1]) + padding_y * 2
    
    # 配置座標
    center_x = target_x
    center_y = target_y
    rect_left = target_x - (w / 2)
    rect_top = target_y - (h / 2)
    rect_right = rect_left + w
    rect_bottom = rect_top + h

    # ルート候補（直線、横優先、縦優先）
    path_straight = [(center_x, center_y), (pin_x, pin_y)]
    path_horz = [(center_x, center_y), (pin_x, center_y), (pin_x, pin_y)]
    path_vert = [(center_x, center_y), (center_x, pin_y), (pin_x, pin_y)]

    best_points = path_straight # 初期値

    # モードによる分岐
    if mode == "自動（建物回避）":
        # 3つのルートの危険度を計算
        score_s = calculate_path_score(image, path_straight)
        score_h = calculate_path_score(image, path_horz)
        score_v = calculate_path_score(image, path_vert)
        
        # 一番安全なルートを選ぶ
        scores = {'直線': score_s, '横ルート': score_h, '縦ルート': score_v}
        best_route = min(scores, key=scores.get)
        
        if best_route == '直線':
            best_points = path_straight
        elif best_route == '横ルート':
            best_points = path_horz
        else:
            best_points = path_vert
            
    elif mode == "直線固定":
        best_points = path_straight
    elif mode == "カギ型（横優先）":
        best_points = path_horz
    elif mode == "カギ型（縦優先）":
        best_points = path_vert

    # 線を描く（赤色・太さ3）
    line_color = "red"
    line_width = 3
    for i in range(len(best_points) - 1):
        draw.line([best_points[i], best_points[i+1]], fill=line_color, width=line_width)

    # 白い箱を描く（不透明）
    draw.rectangle((rect_left, rect_top, rect_right, rect_bottom), fill="white", outline="red", width=3)
    
    # 文字を描く
    text_x = rect_left + padding_x
    text_y = rect_top + padding_y - bbox[1]
    draw.text((text_x, text_y), label_text, font=font, fill="black")
    
    return image

# --- 4. アプリ画面の構成 ---
st.set_page_config(page_title="マップ作成ツール", page_icon="📍")
st.title("📍 建築現場マップ作成ツール")
st.markdown("道路の上など、**文字を置きたい場所をクリック**してください。AIが**薄いグレー（建物）**を避けて線を引きます。")

# サイドバー設定
st.sidebar.title("設定")
label_text = st.sidebar.text_input("吹き出しの文字", "建築現場")

line_mode = st.sidebar.selectbox(
    "線の引き方",
    ("自動（建物回避）", "直線固定", "カギ型（横優先）", "カギ型（縦優先）")
)

uploaded_file = st.file_uploader("画像をアップロード", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    
    # 画面幅に合わせてリサイズ（クリック座標を正しく取るため）
    base_width = 700
    w_percent = (base_width / float(image.size[0]))
    h_size = int((float(image.size[1]) * float(w_percent)))
    resized_image = image.resize((base_width, h_size), Image.Resampling.LANCZOS)

    st.info("👇 **画像の上をクリックして場所を指定してください**")
    
    # クリック検知パーツ
    coords = streamlit_image_coordinates(resized_image, key="click")

    if coords:
        target_x = coords['x']
        target_y = coords['y']
    else:
        # まだクリックしてない時はとりあえず左上に
        target_x = 100
        target_y = 100

    # 画像を作成
    result_image = draw_label(resized_image.copy(), target_x, target_y, label_text, line_mode)
    
    # 表示
    st.image(result_image)

    # ダウンロードボタン
    buf = io.BytesIO()
    result_image.save(buf, format="PNG")
    st.download_button("📥 画像をダウンロード", buf.getvalue(), "挨拶チラシ地図.png", "image/png")

