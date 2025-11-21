import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import io
import cv2
import numpy as np

def get_pin_tip_position(pil_image):
    """
    画像の中から「赤いピン」を探し、その先端（一番下の座標）を返します。
    見つからない場合は、画像の中心を返します。
    """
    # PIL画像をOpenCV形式（数値の配列）に変換
    img_array = np.array(pil_image)
    
    # 色の空間をRGBからHSV（色相・彩度・明度）に変換
    # ※OpenCVで扱いやすくするため
    hsv = cv2.cvtColor(img_array, cv2.COLOR_RGB2HSV)

    # 「赤色」の範囲を定義（赤は2つの範囲にまたがることが多い）
    # 範囲1: 0〜10
    lower_red1 = np.array([0, 70, 50])
    upper_red1 = np.array([10, 255, 255])
    # 範囲2: 170〜180
    lower_red2 = np.array([170, 70, 50])
    upper_red2 = np.array([180, 255, 255])

    # 画像から赤色だけを抜き出すマスクを作成
    mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
    mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
    mask = mask1 + mask2

    # 赤い領域の輪郭（形）を検出
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if contours:
        # 一番大きな赤い領域（＝ピンの可能性が高い）を選ぶ
        largest_contour = max(contours, key=cv2.contourArea)
        
        # その領域の中で「一番下の点（Y座標が最大の点）」を探す ＝ ピンの先端
        # contourは (x, y) のリスト
        bottom_point = largest_contour[largest_contour[:, :, 1].argmax()][0]
        
        return int(bottom_point[0]), int(bottom_point[1])
    
    else:
        # 赤い色が見つからない場合は、とりあえず画像の中心を返す
        return pil_image.width // 2, pil_image.height // 2

def add_label_with_line(image):
    draw = ImageDraw.Draw(image)
    
    # --- 設定エリア ---
    text = "建築現場"
    text_color = "black"
    box_color = "red"
    line_color = "red"
    line_width = 2
    box_line_width = 2
    font_size = 40

    # ★ここが自動化ポイント★
    # 自動でピンの先端座標を取得します
    pin_x, pin_y = get_pin_tip_position(image)

    # 2. ラベルを置く位置（ピンから見て左上）
    # ピンの位置を基準にするので、常に良い感じの位置になります
    label_x = pin_x - 250
    label_y = pin_y - 250
    # ----------------

    # フォント設定
    try:
        font = ImageFont.truetype("ipaexg.ttf", font_size)
    except:
        font = ImageFont.load_default()

    # サイズ計算
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    padding_x, padding_y = 15, 10

    rect_left, rect_top = label_x, label_y
    rect_right = label_x + text_width + padding_x * 2
    rect_bottom = label_y + text_height + padding_y * 2
    
    # 描画
    # 枠の右下の角から線を引く
    line_start_x, line_start_y = rect_right, rect_bottom
    
    draw.line([(line_start_x, line_start_y), (pin_x, pin_y)], fill=line_color, width=line_width)
    draw.rectangle((rect_left, rect_top, rect_right, rect_bottom), fill="white")
    draw.rectangle((rect_left, rect_top, rect_right, rect_bottom), outline=box_color, width=box_line_width)
    draw.text((label_x + padding_x, label_y + padding_y - bbox[1]), text, font=font, fill=text_color)
    
    return image

st.set_page_config(page_title="建築現場マップ作成ツール", page_icon="📍")
st.title("📍 建築現場マップ作成ツール（自動認識版）")
st.markdown("画像内の**赤いピン**を自動で探し出し、その先端に線を引きます。")

uploaded_file = st.file_uploader("👇 ここに地図画像をドラッグ＆ドロップ", type=["png", "jpg", "jpeg"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.subheader("完成イメージ")
    # コピーを渡して処理
    processed_image = add_label_with_line(image.copy())
    st.image(processed_image, use_column_width=True)

    # ダウンロードボタン
    buf = io.BytesIO()
    processed_image.save(buf, format="PNG")
    byte_im = buf.getvalue()
    
    st.download_button(
        label="📥 画像をダウンロードする",
        data=byte_im,
        file_name="processed_map_auto.png",
        mime="image/png"

    )
