import streamlit as st
from PIL import Image
import google.generativeai as genai
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
import io
import requests
import base64
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as patches
import os
import time
import itertools
import re

# ----------------------------------------------------------
# [1] 기본 설정
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫", layout="centered")

MODELS_TO_TRY = [
    "gemini-2.5-pro",           
    "gemini-2.5-flash",         
    "gemini-3-flash-preview",    
    "gemini-2.0-flash-lite-001" 
]

SHEET_ID = "1zJ2rs68pSE9Ntesg1kfqlI7G22ovfxX8Fb7v7HgxzuQ"

try:
    API_KEYS = [
        st.secrets["GOOGLE_API_KEY"],
        st.secrets.get("GOOGLE_API_KEY_2", st.secrets["GOOGLE_API_KEY"]),
        st.secrets.get("GOOGLE_API_KEY_3", st.secrets["GOOGLE_API_KEY"]),
        st.secrets.get("GOOGLE_API_KEY_4", st.secrets["GOOGLE_API_KEY"])
    ]
    IMGBB_API_KEY = st.secrets["IMGBB_API_KEY"]
except:
    st.error("설정 오류: Secrets 키 확인 필요")
    st.stop()

if 'key_index' not in st.session_state:
    st.session_state['key_index'] = 0

# ----------------------------------------------------------
# [2] 유틸리티 함수
# ----------------------------------------------------------
@st.cache_resource
def get_sheet_client():
    try:
        secrets = st.secrets["gcp_service_account"]
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(secrets, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except: return None

@st.cache_resource
def get_handwriting_font_prop():
    font_file = "NanumPen.ttf"
    if not os.path.exists(font_file):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumpenscript/NanumPenScript-Regular.ttf"
        try:
            r = requests.get(url)
            with open(font_file, "wb") as f:
                f.write(r.content)
        except: pass
    try: return fm.FontProperties(fname=font_file)
    except: return None

def resize_image(image, max_width=800):
    w, h = image.size
    if w > max_width:
        ratio = max_width / float(w)
        new_h = int((float(h) * float(ratio)))
        image = image.resize((max_width, new_h), Image.Resampling.LANCZOS)
    return image

def upload_to_imgbb(image_bytes):
    url = "https://api.imgbb.com/1/upload"
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"key": IMGBB_API_KEY, "image": encoded_image}
    try:
        response = requests.post(url, data=payload, timeout=15)
        if response.status_code == 200:
            return response.json()['data']['url']
        return None
    except: return None

def save_result_to_sheet(student_name, subject, unit, summary, link):
    client = get_sheet_client()
    if not client: return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([now, student_name, subject, unit, summary, link, "", 0])
        st.toast("✅ 저장 완료!", icon="💾")
    except: pass

def increment_review_count(row_date, student_name):
    client = get_sheet_client()
    if not client: return False
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        records = sheet.get_all_records()
        row_idx = -1
        current_count = 0
        for i, record in enumerate(records):
            if str(record.get('날짜')) == str(row_date) and str(record.get('이름')) == str(student_name):
                row_idx = i + 2
                current_count = record.get('복습횟수')
                if current_count == '' or current_count is None: current_count = 0
                break
        if row_idx != -1:
            sheet.update_cell(row_idx, 8, int(current_count) + 1)
            return True
        return False
    except: return False

def load_user_results(user_name):
    client = get_sheet_client()
    if not client: return pd.DataFrame()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        return pd.DataFrame(sheet.get_all_records())
    except: return pd.DataFrame()

def load_students_from_sheet():
    client = get_sheet_client()
    if not client: return None
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("students")
        return pd.DataFrame(sheet.get_all_records())
    except: return None

def clean_text_for_plot_safe(text):
    if not text: return ""
    text = text.replace(r'\iff', '<=>').replace(r'\implies', '=>')
    return text

def text_for_plot_fallback(text):
    if not text: return ""
    return re.sub(r'[\$\\\{\}]', '', text)

def create_solution_image(original_image, hints):
    font_prop = get_handwriting_font_prop()
    w, h = original_image.size
    aspect = h / w
    note_height_ratio = 0.5 
    fig_width = 10
    fig_height = fig_width * (aspect + note_height_ratio)
    
    fig = plt.figure(figsize=(fig_width, fig_height))
    gs = fig.add_gridspec(2, 1, height_ratios=[aspect, note_height_ratio], hspace=0)
    
    ax_img = fig.add_subplot(gs[0])
    ax_img.imshow(original_image)
    ax_img.axis('off')
    
    ax_note = fig.add_subplot(gs[1])
    ax_note.axis('off')
    ax_note.set_facecolor('#FFFACD') 
    rect = patches.Rectangle((0,0), 1, 1, transform=ax_note.transAxes, color='#FFFACD', zorder=0)
    ax_note.add_patch(rect)
    ax_note.plot([0, 1], [1, 1], transform=ax_note.transAxes, color='gray', linestyle='--', linewidth=1)

    try:
        safe_hints = clean_text_for_plot_safe(hints)
        ax_note.text(0.05, 0.88, "💡 1타 강사의 핵심 Point", fontsize=24, color='#FF4500', fontweight='bold', va='top', ha='left', transform=ax_note.transAxes, fontproperties=font_prop)
        lines = safe_hints.split('\n')
        y_pos = 0.72
        for line in lines:
            if line.strip():
                ax_note.text(0.05, y_pos, f"• {line.strip()}", fontsize=21, color='#333333', va='top', ha='left', transform=ax_note.transAxes, fontproperties=font_prop)
                y_pos -= 0.12
        fig.canvas.draw()
    except:
        ax_note.clear()
        ax_note.axis('off')
        ax_note.add_patch(rect)
        fallback_hints = text_for_plot_fallback(hints)
        ax_note.text(0.05, 0.85, "💡 1타 강사의 핵심 Point", fontsize=24, color='#FF4500', fontweight='bold', va='top', ha='left', transform=ax_note.transAxes, fontproperties=font_prop)
        ax_note.text(0.05, 0.65, fallback_hints, fontsize=21, color='#333333', va='top', ha='left', transform=ax_note.transAxes, wrap=True, fontproperties=font_prop)

    buf = io.BytesIO()
    plt.savefig(buf, format='jpg', bbox_inches='tight', pad_inches=0)
    buf.seek(0)
    plt.close(fig)
    return Image.open(buf)

def generate_content_with_fallback(prompt, image=None):
    last_error = None
    for model_name in MODELS_TO_TRY:
        try:
            current_key_idx = st.session_state['key_index']
            current_key = API_KEYS[current_key_idx]
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel(model_name)
            if image:
                response = model.generate_content([prompt, image])
            else:
                response = model.generate_content(prompt)
            st.session_state['key_index'] = (current_key_idx + 1) % len(API_KEYS)
            return response.text, f"✅ {model_name}"
        except Exception as e:
            last_error = e
            st.session_state['key_index'] = (st.session_state['key_index'] + 1) % len(API_KEYS)
            time.sleep(1) 
            continue
    raise last_error

# ----------------------------------------------------------
# [3] 로그인 & 세션
# ----------------------------------------------------------
if 'is_logged_in' not in st.session_state:
    st.session_state['is_logged_in'] = False
if 'analysis_result' not in st.session_state:
    st.session_state['analysis_result'] = None
if 'gemini_image' not in st.session_state:
    st.session_state['gemini_image'] = None
if 'solution_image' not in st.session_state:
    st.session_state['solution_image'] = None

def login_page():
    st.markdown("<h1 style='text-align: center;'>🔒 MA학원 로그인</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        user_id = st.text_input("아이디")
        user_pw = st.text_input("비밀번호", type="password")
        if st.button("로그인", use_container_width=True):
            with st.spinner("접속 중..."):
                df = load_students_from_sheet()
            if df is not None and not df.empty:
                df['id'] = df['id'].astype(str)
                df['pw'] = df['pw'].astype(str)
                user_data = df[df['id'] == user_id]
                if not user_data.empty and user_data.iloc[0]['pw'] == user_pw:
                    st.session_state['is_logged_in'] = True
                    st.session_state['user_name'] = user_data.iloc[0]['name']
                    st.rerun()
                else: st.error("정보 불일치")
            else: st.error("접속 실패")

if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

# ----------------------------------------------------------
# [4] 메인 화면
# ----------------------------------------------------------
with st.sidebar:
    st.success(f"👋 {st.session_state['user_name']} 학생")
    menu = st.radio("메뉴 선택", ["📸 문제 풀기", "📒 내 오답 노트"])
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.session_state['analysis_result'] = None
        st.session_state['solution_image'] = None
        st.rerun()

if menu == "📸 문제 풀기":
    st.markdown("### 🏫 MA학원 AI 오답 도우미")
    st.markdown("##### 1. 과목을 먼저 선택하세요")
    
    subject_options = ["선택안함", "초4 수학", "초5 수학", "초6 수학", "중1 수학", "중2 수학", "중3 수학", "--- 2022 개정 ---", "[22개정] 공통수학1", "[22개정] 공통수학2", "[22개정] 대수", "[22개정] 미적분1", "[22개정] 확통", "--- 2015 개정 ---", "[15개정] 수학(상/하)", "[15개정] 수1", "[15개정] 수2", "[15개정] 미적분", "[15개정] 확통", "[15개정] 기하"]
    selected_subject = st.selectbox("현재 과정을 선택해주세요:", subject_options)

    if selected_subject == "선택안함" or "---" in selected_subject:
        st.info("👆 과목 선택 후 시작해주세요.")
        st.stop()

    tone = "친절하게" if any(x in selected_subject for x in ["초", "중1", "중2"]) else "간결하고 수식 위주로"

    st.markdown("---")
    st.markdown("##### 2. 문제 업로드")
    tab1, tab2 = st.tabs(["📸 카메라", "📂 갤러리"])
    img_file = None
    with tab1:
        cam = st.camera_input("촬영")
        if cam: img_file = cam
    with tab2:
        up = st.file_uploader("파일 선택", type=['jpg', 'png', 'jpeg'])
        if up: img_file = up

    if img_file:
        raw_image = Image.open(img_file)
        if raw_image.mode in ("RGBA", "P"): raw_image = raw_image.convert("RGB")
        st.image(raw_image, caption="선택된 문제", width=400)

        if st.button("🔍 1타 강사 분석 시작", type="primary"):
            with st.spinner("분석 중..."):
                st.session_state['gemini_image'] = resize_image(raw_image)
                try:
                    prompt = f"""
                    당신은 대치동 수학 강사입니다. 과목:{selected_subject}, 말투:{tone}
                    **반드시 아래 구분자를 정확히 포함하여 답변하세요.**
                    
                    ===이미지용_힌트===
                    (단원/공식/힌트 한 줄 형태로 3~4줄 줄바꿈 작성)
                    
                    ===상세풀이_텍스트===
                    [1] 정석 풀이 (The Direct Path)
                    (단계별로 줄바꿈을 하여 간결하게 작성)
                    
                    [2] 🍯 숏컷 풀이 (The Genius Shortcut)
                    (기발한 풀이가 있다면 줄바꿈하여 작성, 없으면 '없음'으로 간단히 작성)
                    
                    ===쌍둥이문제===
                    (문제 내용)
                    (LaTeX 사용, 줄바꿈 필수)
                    ===정답및해설===
                    (LaTeX 사용, 단계별로 줄바꿈을 하여 간결하게 작성)
                    """
                    result_text, used_model = generate_content_with_fallback(prompt, st.session_state['gemini_image'])
                    st.session_state['analysis_result'] = result_text
                    st.session_state['used_model'] = used_model
                    
                    # 🔥 [안전 파싱 로직] 구분자 유무 확인
                    img_hint = "분석 실패"
                    if "===이미지용_힌트===" in result_text and "===상세풀이_텍스트===" in result_text:
                        img_hint = result_text.split("===이미지용_힌트===")[1].split("===상세풀이_텍스트===")[0].strip()
                    
                    st.session_state['solution_image'] = create_solution_image(st.session_state['gemini_image'], img_hint)
                    
                    img_byte_arr = io.BytesIO()
                    st.session_state['solution_image'].save(img_byte_arr, format='JPEG', quality=90)
                    link = upload_to_imgbb(img_byte_arr.getvalue()) or "이미지_없음"
                    save_result_to_sheet(st.session_state['user_name'], selected_subject, img_hint.split('\n')[0][:20], result_text, link)
                    st.rerun()
                except Exception as e:
                    st.error(f"오류 발생: {e}")

    # 🔥 [수정] IndexError 방어 파싱
    if st.session_state['analysis_result']:
        full_text = st.session_state['analysis_result']
        parts = {"sol": "풀이 분석 중..", "prob": "문제 생성 중..", "ans": "해설 생성 중.."}
        
        try:
            if "===상세풀이_텍스트===" in full_text:
                temp = full_text.split("===상세풀이_텍스트===")[1]
                if "===쌍둥이문제===" in temp:
                    parts["sol"] = temp.split("===쌍둥이문제===")[0].strip()
                    temp = temp.split("===쌍둥이문제===")[1]
                    if "===정답및해설===" in temp:
                        parts["prob"] = temp.split("===정답및해설===")[0].strip()
                        parts["ans"] = temp.split("===정답및해설===")[1].strip()
                    else: parts["prob"] = temp
                else: parts["sol"] = temp
        except Exception as e:
            st.warning("일부 내용을 파싱하는 데 실패했습니다. 원문으로 표시합니다.")
            parts["sol"] = full_text

        st.markdown("---")
        if st.session_state['solution_image']:
            st.image(st.session_state['solution_image'], use_container_width=True)
            
        with st.expander("📖 상세 풀이 (정석 & 숏컷)", expanded=True):
            st.markdown(parts["sol"])
        st.markdown("### 📝 쌍둥이 문제")
        st.write(parts["prob"])
        with st.expander("🔐 정답 보기"):
            st.write(parts["ans"])

elif menu == "📒 내 오답 노트":
    st.markdown("### 📒 내 오답 노트 리스트")
    df = load_user_results(st.session_state['user_name'])
    if not df.empty:
        my_notes = df[df['이름'] == st.session_state['user_name']].sort_values(by='날짜', ascending=False)
        for index, row in my_notes.iterrows():
            with st.expander(f"📅 {row.get('날짜', '')} | {row.get('과목', '')}"):
                if row.get('링크') != "이미지_없음": st.image(row.get('링크'), use_container_width=True)
                st.write(row.get('내용', ''))
                if st.button("✅ 복습", key=f"rev_{index}"):
                    if increment_review_count(row.get('날짜'), row.get('이름')): st.rerun()
