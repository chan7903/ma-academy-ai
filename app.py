import streamlit as st
import extra_streamlit_components as stx
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
import json
import re
import random 
import ast
import numpy as np
import textwrap

# 🔥 [추가 라이브러리] 판서 및 음성 기능용
from streamlit_drawable_canvas import st_canvas
from streamlit_mic_recorder import speech_to_text

# ----------------------------------------------------------
# [1] 기본 설정 & 디자인 주입 (HTML/Tailwind)
# ----------------------------------------------------------

# 🔥 원장님 학원 로고 URL
LOGO_URL = "https://i.ibb.co/Hp34Pg7v/logo.png"

st.set_page_config(
    page_title="MathAI Pro: Smart Tutor", 
    page_icon=LOGO_URL, 
    layout="wide"
)

# 스마트폰 홈 화면 아이콘 주입
st.markdown(f"""
    <head>
        <link rel="apple-touch-icon" href="{LOGO_URL}">
        <link rel="icon" type="image/png" href="{LOGO_URL}">
        <link rel="shortcut icon" type="image/png" href="{LOGO_URL}">
    </head>
""", unsafe_allow_html=True)

# Tailwind CSS & 폰트 주입
st.markdown("""
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined" rel="stylesheet" />
    
    <style>
        .stApp { background-color: #f6f7f8; font-family: 'Lexend', 'Noto Sans KR', sans-serif; }
        header {visibility: hidden;} 
        .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 100% !important; }
        
        div.stButton > button {
            background-color: #f97316 !important; color: white !important;
            border: none !important; border-radius: 0.5rem !important;
            padding: 0.75rem 1rem !important; font-weight: 700 !important;
            width: 100%; transition: all 0.2s;
        }
        div.stButton > button:hover { background-color: #ea580c !important; transform: scale(0.98); }
        
        .math-card {
            background-color: white; border-radius: 0.75rem;
            border: 1px solid #e5e7eb; box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
            padding: 1.5rem; margin-bottom: 1.5rem;
        }
        
        .stChatMessage { background-color: white; border-radius: 10px; padding: 10px; border: 1px solid #eee; }
        .stChatMessage[data-testid="user-message"] { background-color: #fff7ed; border-color: #fdba74; }
    </style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# [2] 유틸리티 함수 & 설정
# ----------------------------------------------------------

try:
    API_KEYS = []
    if "GOOGLE_API_KEY" in st.secrets:
        API_KEYS.append(st.secrets["GOOGLE_API_KEY"])
    for i in range(1, 101):
        key_name = f"GOOGLE_API_KEY_{i}"
        if key_name in st.secrets:
            API_KEYS.append(st.secrets[key_name])
    API_KEYS = list(set([k for k in API_KEYS if k]))
    
    if not API_KEYS:
        st.error("설정 오류: API 키가 하나도 없습니다.")
        st.stop()
        
    IMGBB_API_KEY = st.secrets["IMGBB_API_KEY"]
except:
    st.error("설정 오류: Secrets 접근 실패")
    st.stop()

# 🔥 [전략 확정] 모델 라인업 (안정성 + 지능)
FLASH_MODELS = [
    "gemini-2.5-flash",           
    "gemini-2.0-flash",           
    "gemini-flash-latest"         
]

PRO_MODELS = [
    "gemini-3-flash-preview",     
    "gemini-2.0-flash-exp",       
    "gemini-2.5-flash"            
]

# 🔥 [핵심] 교육과정 정밀 매핑 (Grade-Lock System)
CURRICULUM_GUIDE = {
    "default": "해당 학년의 교과서 개념만 사용할 것. 선행 학습 개념 사용 금지.",
    "[22개정] 공통수학1": "✅ **[행렬(Matrix)] 사용 허용.** 케일리-해밀턴 등 심화 개념 가능.",
    "[15개정] 수학(하)": "⛔ **[행렬] 절대 사용 금지.** (교육과정에 없음).",
    "[22개정] 확률과 통계": "✅ **[모비율 추정]** 강조. ⛔ **[원순열] 공식 지양.** 기본 순열 원리로 설명.",
    "[15개정] 확률과 통계": "✅ **[원순열]** 공식 사용 가능.",
    "수학II": "⛔ **[이계도함수($f''$), 변곡점] 정석 풀이에서 절대 금지.** (오직 증감표로만 설명). ⛔ **[로피탈]** 정석 풀이에서 금지.",
    "미적분": "삼각함수/지수로그함수 미분, 변곡점, 이계도함수 허용.",
    "중": "고등학교 과정(미분, 행렬 등) 절대 사용 금지. 기하학적 성질로만 설명."
}

def get_curriculum_prompt(subject):
    prompt = CURRICULUM_GUIDE.get("default")
    for key, rule in CURRICULUM_GUIDE.items():
        if key in subject or (key == "수학II" and ("수학II" in subject or "수학2" in subject)):
            prompt += "\n" + rule
    return prompt

SHEET_ID = "1zJ2rs68pSE9Ntesg1kfqlI7G22ovfxX8Fb7v7HgxzuQ"

if 'key_index' not in st.session_state: st.session_state['key_index'] = 0

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

def save_result_to_sheet(student_name, subject, unit, summary, link, chat_log):
    client = get_sheet_client()
    if not client: return None
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        kst = datetime.timezone(datetime.timedelta(hours=9))
        now = datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            data = summary.copy() 
            data['chat_history'] = chat_log
            final_content = str(data) 
        except:
            final_content = str(summary)

        sheet.append_row([now, student_name, subject, unit, final_content, link, "", 0])
        st.toast("✅ 학습 기록 저장 완료!", icon="💾")
        return now 
    except: return None

def overwrite_result_in_sheet(student_name, target_time, new_summary):
    client = get_sheet_client()
    if not client: return False
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        records = sheet.get_all_records()
        row_idx = -1
        
        for i, record in enumerate(records):
            if str(record.get('날짜')) == str(target_time) and str(record.get('이름')) == str(student_name):
                row_idx = i + 2
                current_content_str = record.get('내용')
                break
        
        if row_idx != -1:
            try:
                data = ast.literal_eval(current_content_str)
                data.update(new_summary)
                updated_content = str(data)
                sheet.update_cell(row_idx, 5, updated_content)
                return True
            except: return False
        return False
    except: return False

def update_chat_log_in_sheet(student_name, target_time, new_chat_log):
    client = get_sheet_client()
    if not client: return False
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        records = sheet.get_all_records()
        row_idx = -1
        
        for i, record in enumerate(records):
            if str(record.get('날짜')) == str(target_time) and str(record.get('이름')) == str(student_name):
                row_idx = i + 2
                current_content_str = record.get('내용')
                break
        
        if row_idx != -1:
            try:
                data = ast.literal_eval(current_content_str)
                data['chat_history'] = new_chat_log
                updated_content = str(data)
                sheet.update_cell(row_idx, 5, updated_content)
                return True
            except: return False
        return False
    except: return False

def update_twin_data_in_sheet(student_name, target_time, twin_data):
    client = get_sheet_client()
    if not client: return False
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        records = sheet.get_all_records()
        row_idx = -1
        
        for i, record in enumerate(records):
            if str(record.get('날짜')) == str(target_time) and str(record.get('이름')) == str(student_name):
                row_idx = i + 2
                current_content_str = record.get('내용')
                break
        
        if row_idx != -1:
            try:
                data = ast.literal_eval(current_content_str)
                data['twin_problem'] = twin_data.get('twin_problem')
                data['twin_answer'] = twin_data.get('twin_answer')
                updated_content = str(data)
                sheet.update_cell(row_idx, 5, updated_content)
                return True
            except: return False
        return False
    except: return False

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

@st.cache_data(ttl=600)
def load_students_from_sheet():
    client = get_sheet_client()
    if not client: return None
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("students")
        all_data = sheet.get_all_values()
        if not all_data: return None
        headers = all_data.pop(0) 
        return pd.DataFrame(all_data, columns=headers)
    except: return None

def clean_text_for_plot_safe(text):
    if not text: return ""
    text = text.replace(r'\iff', '⇔').replace(r'\implies', '⇒')
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
        
        pre_lines = safe_hints.replace(' / ', '\n').split('\n')
        
        y_pos = 0.72
        for line in pre_lines:
            line = line.strip()
            if not line: continue
            
            wrapped_lines = textwrap.wrap(line, width=42)
            
            for i, w_line in enumerate(wrapped_lines):
                prefix = "• " if i == 0 else "  "
                ax_note.text(0.05, y_pos, f"{prefix}{w_line}", fontsize=21, color='#333333', va='top', ha='left', transform=ax_note.transAxes, fontproperties=font_prop)
                y_pos -= 0.09 
                
        fig.canvas.draw()
    except:
        ax_note.clear()
        ax_note.axis('off')
        ax_note.add_patch(rect)
        fallback_hints = text_for_plot_fallback(hints)
        ax_note.text(0.05, 0.85, "💡 1타 강사의 핵심 Point", fontsize=24, color='#FF4500', fontweight='bold', va='top', ha='left', transform=ax_note.transAxes, fontproperties=font_prop)
        
        wrapped_fallback = textwrap.fill(fallback_hints, width=40)
        ax_note.text(0.05, 0.65, wrapped_fallback, fontsize=21, color='#333333', va='top', ha='left', transform=ax_note.transAxes, fontproperties=font_prop)

    buf = io.BytesIO()
    plt.savefig(buf, format='jpg', bbox_inches='tight', pad_inches=0)
    buf.seek(0)
    plt.close(fig)
    return Image.open(buf)

def generate_content_with_fallback(prompt, image=None, mode="flash", status_container=None, text_placeholder=None):
    last_error = None
    key_indices = list(range(len(API_KEYS)))
    random.shuffle(key_indices)

    if mode == "pro":
        target_models = PRO_MODELS
    else:
        target_models = FLASH_MODELS

    for model_name in target_models:
        for key_idx in key_indices:
            current_key = API_KEYS[key_idx]
            try:
                genai.configure(api_key=current_key)
                model = genai.GenerativeModel(model_name)
                
                if image: 
                    response_stream = model.generate_content([prompt, image], stream=True)
                else: 
                    response_stream = model.generate_content(prompt, stream=True)
                
                full_text = ""
                for chunk in response_stream:
                    if chunk.text:
                        full_text += chunk.text
                        if status_container:
                            if "===SOLUTION===" in full_text and "===TWIN_PROBLEM===" not in full_text:
                                status_container.update(label="✍️ 2. 해설지 작성 중...", state="running")
                            elif "===TWIN_PROBLEM===" in full_text:
                                status_container.update(label="👯‍♀️ 3. 쌍둥이 문제 창작 중...", state="running")
                            elif "===CONCEPT===" in full_text:
                                status_container.update(label="🔍 1. 문제 분석 중...", state="running")
                        
                        if text_placeholder:
                            text_placeholder.markdown(full_text + "▌")
                
                return full_text, f"✅ {model_name}"
            
            except Exception as e:
                last_error = e
                time.sleep(0.5) 
                continue
    
    raise last_error

# 🔥 [수정] Pro 모델 출력 오류 방지를 위한 정밀 Regex 분류기
def parse_response_to_dict(text):
    data = {}
    # Pro 모델이 태그에 별(**)이나 띄어쓰기를 넣는 것을 방지하기 위한 정규화
    clean_text = re.sub(r'[\*\#]*={3,}\s*([A-Z_]+)\s*={3,}[\*\#]*', r'===\1===', text)
    
    try:
        if "===CONCEPT===" in clean_text:
            data['concept'] = clean_text.split("===CONCEPT===")[1].split("===HINT===")[0].strip()
        else: data['concept'] = "개념 분석 실패"
        
        if "===HINT===" in clean_text:
            data['hint_for_image'] = clean_text.split("===HINT===")[1].split("===SOLUTION===")[0].strip()
        else: data['hint_for_image'] = "힌트 없음"
        
        if "===SOLUTION===" in clean_text:
            data['solution'] = clean_text.split("===SOLUTION===")[1].split("===SHORTCUT===")[0].strip()
        else: data['solution'] = "풀이 생성 실패"
        
        if "===SHORTCUT===" in clean_text:
            data['shortcut'] = clean_text.split("===SHORTCUT===")[1].split("===CORRECTION===")[0].strip()
        else: data['shortcut'] = "숏컷 없음"
        
        if "===CORRECTION===" in clean_text:
            data['correction'] = clean_text.split("===CORRECTION===")[1].split("===TWIN_PROBLEM===")[0].strip()
        else: data['correction'] = "첨삭 없음"

        if "===TWIN_PROBLEM===" in clean_text:
             data['twin_problem'] = clean_text.split("===TWIN_PROBLEM===")[1].split("===TWIN_ANSWER===")[0].strip()
        else: data['twin_problem'] = "쌍둥이 문제 없음"

        if "===TWIN_ANSWER===" in clean_text:
             data['twin_answer'] = clean_text.split("===TWIN_ANSWER===")[1].strip()
        else: data['twin_answer'] = "정답 없음"
            
    except Exception as e:
        data['concept'] = "자동 분석 (Parsing Error)"
        data['solution'] = text
        data['shortcut'] = ""
        data['hint_for_image'] = "오류"

    return data

def sanitize_json(text):
    text = text.replace("```json", "").replace("```", "").strip()
    pattern = r'\\(?!["])' 
    text = re.sub(pattern, r'\\\\', text)
    return text

# ----------------------------------------------------------
# [3] 로그인 & 상태 관리
# ----------------------------------------------------------
if 'is_logged_in' not in st.session_state: st.session_state['is_logged_in'] = False
if 'analysis_result' not in st.session_state: st.session_state['analysis_result'] = None
if 'gemini_image' not in st.session_state: st.session_state['gemini_image'] = None
if 'solution_image' not in st.session_state: st.session_state['solution_image'] = None

if 'chat_active' not in st.session_state: st.session_state['chat_active'] = False
if 'chat_messages' not in st.session_state: st.session_state['chat_messages'] = []
if 'self_note' not in st.session_state: st.session_state['self_note'] = ""
if 'last_canvas_image' not in st.session_state: st.session_state['last_canvas_image'] = None
if 'enable_canvas' not in st.session_state: st.session_state['enable_canvas'] = False
if 'saved_timestamp' not in st.session_state: st.session_state['saved_timestamp'] = None 
if 'last_saved_chat_len' not in st.session_state: st.session_state['last_saved_chat_len'] = 0
if 'last_voice_text' not in st.session_state: st.session_state['last_voice_text'] = ""

cookie_manager = stx.CookieManager(key="auth_cookie")

if not st.session_state['is_logged_in']:
    time.sleep(0.1)
    stored_user_id = cookie_manager.get(cookie="mathai_user_id")
    if stored_user_id:
        df = load_students_from_sheet() 
        if df is not None and not df.empty:
            df['id'] = df['id'].astype(str)
            user_data = df[df['id'] == str(stored_user_id)]
            if not user_data.empty:
                st.session_state['is_logged_in'] = True
                st.session_state['user_name'] = user_data.iloc[0]['name']
                st.toast(f"👋 {st.session_state['user_name']}님, 어서오세요!")
                time.sleep(0.5)
                st.rerun()

def login_page():
    st.markdown("<h1 style='text-align: center; color:#f97316;'>🏫 MathAI Pro 로그인</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown('<div class="math-card">', unsafe_allow_html=True)
        user_id = st.text_input("아이디")
        user_pw = st.text_input("비밀번호", type="password")
        
        if st.button("로그인"):
            with st.spinner("학생 정보를 확인 중입니다..."):
                df = load_students_from_sheet()
            if df is not None and not df.empty:
                df['id'] = df['id'].astype(str)
                df['pw'] = df['pw'].astype(str).apply(lambda x: x.split('.')[0])
                
                user_data = df[df['id'] == user_id]
                if not user_data.empty and user_data.iloc[0]['pw'] == user_pw:
                    st.session_state['is_logged_in'] = True
                    st.session_state['user_name'] = user_data.iloc[0]['name']
                    cookie_manager.set("mathai_user_id", user_id, expires_at=datetime.datetime.now() + datetime.timedelta(days=7))
                    st.success("로그인 성공! 이동합니다...")
                    time.sleep(1)
                    st.rerun()
                else: st.error("정보가 일치하지 않습니다.")
            else: st.error("데이터베이스 연결 실패")
        st.markdown('</div>', unsafe_allow_html=True)

if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

# ----------------------------------------------------------
# [4] UI & 기능
# ----------------------------------------------------------
st.markdown("""
<header class="sticky top-0 z-50 bg-white border-b border-gray-200 px-6 py-3 shadow-sm mb-6">
    <div class="max-w-[1440px] mx-auto flex items-center justify-between">
        <div class="flex items-center gap-4">
            <span class="material-symbols-outlined text-[#f97316] text-3xl">calculate</span>
            <h2 class="text-xl font-bold tracking-tight text-slate-900">MathAI <span class="text-[#f97316]">Pro</span></h2>
        </div>
        <div class="flex items-center gap-2">
            <span class="text-sm font-bold text-slate-600">학생: """ + st.session_state['user_name'] + """</span>
            <div class="bg-gray-100 rounded-full w-8 h-8 flex items-center justify-center">
                <span class="material-symbols-outlined text-gray-500">person</span>
            </div>
        </div>
    </div>
</header>
""", unsafe_allow_html=True)

with st.sidebar:
    with st.expander("📲 앱 설치(아이콘 만들기) 방법 (클릭)", expanded=False):
        st.write("1. (아이폰) 하단 '공유' 버튼 → '홈 화면에 추가'")
        st.write("2. (갤럭시) 우측 상단 '점 3개' → '홈 화면에 추가' 또는 '앱 설치'")

    st.markdown(f"### 👋 반가워요, {st.session_state['user_name']}님!")
    menu = st.radio("학습 메뉴", ["📸 문제 풀기", "📒 내 오답 노트"])
    
    if st.button("🔄 초기화 (새 문제)"):
        st.session_state['chat_active'] = False
        st.session_state['chat_messages'] = []
        st.session_state['analysis_result'] = None
        st.session_state['gemini_image'] = None
        st.session_state['last_canvas_image'] = None
        st.session_state['self_note'] = ""
        st.session_state['enable_canvas'] = False
        st.session_state['saved_timestamp'] = None
        st.session_state['last_saved_chat_len'] = 0
        st.session_state['last_voice_text'] = ""
        st.rerun()
        
    if st.button("로그아웃"):
        cookie_manager.delete("mathai_user_id") 
        st.session_state['is_logged_in'] = False
        time.sleep(0.5)
        st.rerun()

if menu == "📸 문제 풀기":
    if not st.session_state['chat_active']:
        st.markdown("""
        <div class="mb-6">
            <h1 class="text-2xl font-bold text-[#111418]">AI 튜터에게 질문하기</h1>
            <p class="text-slate-500 text-sm">문제를 찍으면 바로 답을 주지 않고, 선생님처럼 차근차근 알려줍니다.</p>
        </div>
        """, unsafe_allow_html=True)

        left_col, right_col = st.columns([1, 1.2], gap="medium")
        with left_col:
            st.markdown('<div class="math-card h-full">', unsafe_allow_html=True)
            st.markdown('<h3 class="font-bold mb-4 text-slate-700">📤 문제 업로드</h3>', unsafe_allow_html=True)
            
            subject_options = [
                "선택안함", 
                "초3 수학", "초4 수학", "초5 수학", "초6 수학",
                "중1 수학", "중2 수학", "중3 수학",
                "--- 2022 개정 교육과정 (고1~) ---",
                "[22개정] 공통수학1", "[22개정] 공통수학2", 
                "[22개정] 대수", "[22개정] 미적분I", 
                "[22개정] 미적분II", "[22개정] 확률과 통계", "[22개정] 기하",
                "--- 2015 개정 교육과정 (고2~3) ---",
                "[15개정] 수학(상)", "[15개정] 수학(하)", 
                "[15개정] 수학I", "[15개정] 수학II", 
                "[15개정] 미적분", "[15개정] 확률과 통계", "[15개정] 기하"
            ]
            selected_subject = st.selectbox("과목/단원", subject_options, label_visibility="collapsed")
            
            if selected_subject == "선택안함" or "---" in selected_subject:
                st.warning("👆 먼저 과목을 선택해주세요.")
                img_file = None
            else:
                tab1, tab2 = st.tabs(["파일 선택", "카메라"])
                img_file = None
                with tab1:
                    img_file = st.file_uploader("이미지", type=['jpg', 'png'], label_visibility="collapsed")
                with tab2:
                    cam = st.camera_input("촬영", label_visibility="collapsed")
                    if cam: img_file = cam

            if img_file:
                image = Image.open(img_file)
                if image.mode in ("RGBA", "P"): image = image.convert("RGB")
                st.image(image, caption="선택한 문제", use_column_width=True)
                st.markdown("<br>", unsafe_allow_html=True)
                
                if st.button("💬 AI 튜터링 시작", type="primary"):
                    st.session_state['gemini_image'] = resize_image(image)
                    st.session_state['selected_subject'] = selected_subject
                    st.session_state['chat_active'] = True
                    st.session_state['chat_messages'] = [
                        {"role": "ai", "content": "문제를 확인했습니다. 같이 차근차근 풀어봅시다. 어디서 막혔나요?"}
                    ]
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        
        with right_col:
            st.markdown("""
            <div class="math-card flex flex-col items-center justify-center text-center h-[400px]">
                <span class="material-symbols-outlined text-gray-300 text-[60px] mb-4">chat_bubble</span>
                <h3 class="text-lg font-bold text-slate-700 mb-2">AI 과외 선생님 대기 중</h3>
                <p class="text-slate-500 text-sm">문제를 올리고 튜터링을 시작해보세요.</p>
            </div>
            """, unsafe_allow_html=True)

    else:
        chat_col_left, chat_col_right = st.columns([1, 1.2], gap="medium")
        
        with chat_col_left:
            st.markdown('<div class="math-card">', unsafe_allow_html=True)
            col_title, col_toggle = st.columns([0.6, 0.4])
            with col_title:
                st.markdown('<h3 class="font-bold mb-2 text-slate-700">📄 문제 & 질문</h3>', unsafe_allow_html=True)
            with col_toggle:
                st.session_state['enable_canvas'] = st.checkbox("🖍️ 판서(그리기) 모드", value=st.session_state['enable_canvas'])

            if st.session_state['gemini_image']:
                if st.session_state['enable_canvas']:
                    orig_w, orig_h = st.session_state['gemini_image'].size
                    canvas_width = 500
                    canvas_height = int(orig_h * (canvas_width / orig_w))
                    
                    canvas_result = st_canvas(
                        fill_color="rgba(255, 165, 0, 0.3)",
                        stroke_width=3,
                        stroke_color="#ff0000",
                        background_image=st.session_state['gemini_image'],
                        update_streamlit=True,
                        height=canvas_height,
                        width=canvas_width,
                        drawing_mode="freedraw",
                        key="canvas",
                    )
                    
                    if canvas_result.image_data is not None:
                        st.session_state['last_canvas_image'] = canvas_result.image_data
                else:
                    st.image(st.session_state['gemini_image'], use_column_width=True)

            st.markdown("---")
            
            st.markdown('<div class="h-[400px] overflow-y-auto flex flex-col relative">', unsafe_allow_html=True)
            for msg in st.session_state['chat_messages']:
                if msg['role'] == 'ai':
                    with st.chat_message("assistant", avatar="🤖"):
                        st.write(msg['content'])
                else:
                    with st.chat_message("user", avatar="🧑‍🎓"):
                        st.write(msg['content'])

            if st.session_state['analysis_result'] and st.session_state['saved_timestamp']:
                if len(st.session_state['chat_messages']) > st.session_state['last_saved_chat_len']:
                    if st.button("💾 추가된 대화 저장하기", type="secondary", use_container_width=True):
                        if update_chat_log_in_sheet(st.session_state['user_name'], st.session_state['saved_timestamp'], st.session_state['chat_messages']):
                            st.session_state['last_saved_chat_len'] = len(st.session_state['chat_messages'])
                            st.toast("대화 내용이 업데이트되었습니다!", icon="✅")
                        else:
                            st.error("저장 실패")

            col_mic, col_text = st.columns([0.1, 0.9])
            with col_mic:
                voice_text = speech_to_text(language='ko', start_prompt="🎤", stop_prompt="⏹️", just_once=False, use_container_width=True)
            
            with col_text:
                chat_input_text = st.chat_input("질문을 입력하세요 (타자, 음성, 판서 모두 가능)")
            
            final_prompt = None
            if voice_text and voice_text != st.session_state['last_voice_text']:
                final_prompt = voice_text
                st.session_state['last_voice_text'] = voice_text 
            elif chat_input_text:
                final_prompt = chat_input_text

            if final_prompt:
                st.session_state['chat_messages'].append({"role": "user", "content": final_prompt})
                st.rerun()

            if st.session_state['chat_messages'] and st.session_state['chat_messages'][-1]['role'] == 'user':
                with st.spinner("선생님이 답변을 생각 중입니다..."):
                    try:
                        history_text = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state['chat_messages']])
                        
                        context_injection = ""
                        if st.session_state['analysis_result']:
                            res = st.session_state['analysis_result']
                            context_injection = f"""
                            [참고: 너는 이미 이 문제의 정석 풀이와 숏컷을 학생에게 알려주었어.]
                            - 정석 풀이: {res.get('solution')}
                            - 숏컷 풀이: {res.get('shortcut')}
                            학생이 이 풀이에 대해 추가 질문을 하고 있으니, 위 내용을 바탕으로 답변해줘.
                            """

                        # 🔥 [채팅 프롬프트: 정석 우선 원칙]
                        tutor_prompt = f"""
                        당신은 친절하지만 **교과서적인 풀이를 중시하는** 학교 수학 선생님입니다. 
                        과목: {st.session_state['selected_subject']}
                        
                        {context_injection}

                        [대화 내역] 
                        {history_text}
                        
                        [지시사항]
                        1. 학생이 먼저 묻지 않는 한, **'숏컷'이나 '로피탈', '변곡점' 같은 기술은 절대 먼저 꺼내지 마세요.**
                        2. 교과서에 나오는 **정석적인 방법(증감표, 정의 등)**으로만 설명하세요.
                        3. 수식은 LaTeX($$)를 사용하고, 답변은 3문장 이내로 간결하게 하세요.
                        """
                        
                        img_to_send = st.session_state['gemini_image']
                        if st.session_state['enable_canvas'] and st.session_state.get('last_canvas_image') is not None:
                            img_array = st.session_state['last_canvas_image'].astype('uint8')
                            img_to_send = Image.fromarray(img_array, 'RGBA').convert('RGB')

                        response_text, _ = generate_content_with_fallback(tutor_prompt, img_to_send, mode="flash")
                        st.session_state['chat_messages'].append({"role": "ai", "content": response_text})
                        st.rerun()
                    except Exception as e:
                        st.error(f"채팅 오류: {e}")
            st.markdown('</div></div>', unsafe_allow_html=True)

        with chat_col_right:
            st.markdown('<div class="math-card" style="border-left: 5px solid #f97316;">', unsafe_allow_html=True)
            st.markdown('<h3 class="font-bold mb-2 text-[#f97316]">✍️ 나의 깨달음 정리 (Self-Note)</h3>', unsafe_allow_html=True)
            st.markdown('<p class="text-xs text-slate-500 mb-2">선생님과 대화하며 알게 된 힌트나 핵심을 적어보세요. (나중에 오답노트에 저장됩니다)</p>', unsafe_allow_html=True)
            
            self_note_input = st.text_area("내용 입력", value=st.session_state['self_note'], height=150, label_visibility="collapsed", placeholder="예: 판별식 D가 0보다 커야 실근 2개를 갖는다는 걸 깜빡했다.")
            if st.button("💾 정리 내용 임시 저장"):
                st.session_state['self_note'] = self_note_input
                st.toast("정리 내용이 저장되었습니다.")
            st.markdown('</div>', unsafe_allow_html=True)

            if not st.session_state['analysis_result']:
                st.info("💡 충분히 고민하고 정리를 마쳤다면, 아래 버튼을 눌러 해설을 확인하세요.")
                if st.button("🔐 정답 및 1타 풀이 공개 (저장)", type="primary"):
                    status_container = st.status("🚀 AI 튜터가 문제를 분석하고 있습니다...", expanded=True)
                    text_placeholder = st.empty() 
                    
                    # 🔥 [Flash 프롬프트: 교과서적 정석 풀이 강제 + 교육과정 필터 적용]
                    curriculum_rules = get_curriculum_prompt(st.session_state['selected_subject'])
                    
                    final_prompt_main = f"""
                    당신은 권위 있는 수학 교과서 및 해설지 집필 위원입니다. (과목: {st.session_state['selected_subject']})
                    이미지를 분석하여 정석 풀이와 숏컷을 구분하여 작성하십시오.

                    **[교육과정 준수 지침 (Grade-Lock)]**
                    {curriculum_rules}

                    **[작성 스타일 지침]**
                    1. **건조한 문어체 사용:** '~요' 체를 금지하고, '~다', '~임', '~함'으로 끝내십시오. 감탄사나 불필요한 서론을 제거하십시오.
                    2. **구조화된 리스트:** 풀이 과정이 길어지면 번호(1., 2.)를 매겨 단계별로 구분하십시오.
                    3. **학생 노트 참고:** {st.session_state['self_note']}

                    **[출력 형식]**
                    ===CONCEPT===
                    (핵심 개념 한 줄)
                    ===HINT===
                    (단원명 / 힌트 1줄)
                    ===SOLUTION===
                    (### 📖 [1] 정석 풀이 (Standard)
                    **[지침 준수]**: 위 교육과정 규칙을 철저히 지키며, 교과서적인 서술형 풀이를 작성. 번호 매기기 필수. 선행 개념 절대 금지.)
                    ===SHORTCUT===
                    (### 🍯 [2] 숏컷 풀이 (Shortcut)
                    실전 문제 풀이용 스킬. 여기서는 선행 개념(로피탈, 비율관계 등) 사용 가능. 자유롭게 기술.)
                    ===CORRECTION===
                    (학생의 오개념 교정. [총평], [틀린 부분], [교정] 순서.)
                    ===TWIN_PROBLEM===
                    (유사 문제 1개)
                    ===TWIN_ANSWER===
                    (정답 및 간단 해설)
                    """
                    try:
                        res_text, _ = generate_content_with_fallback(final_prompt_main, st.session_state['gemini_image'], mode="flash", status_container=status_container, text_placeholder=text_placeholder)
                        
                        text_placeholder.empty() 
                        status_container.update(label="✅ 분석 및 창작 완료!", state="complete", expanded=False)
                        
                        data = parse_response_to_dict(res_text)
                        data['my_self_note'] = st.session_state['self_note']
                        
                        st.session_state['analysis_result'] = data
                        
                        st.session_state['solution_image'] = create_solution_image(
                            st.session_state['gemini_image'], data.get('hint_for_image', '힌트 없음')
                        )
                        img_byte_arr = io.BytesIO()
                        st.session_state['solution_image'].save(img_byte_arr, format='JPEG', quality=90)
                        link = upload_to_imgbb(img_byte_arr.getvalue()) or "이미지_없음"
                        
                        saved_ts = save_result_to_sheet(
                            st.session_state['user_name'], 
                            st.session_state['selected_subject'], 
                            data.get('concept'), 
                            data, 
                            link,
                            st.session_state['chat_messages']
                        )
                        st.session_state['saved_timestamp'] = saved_ts
                        st.session_state['last_saved_chat_len'] = len(st.session_state['chat_messages'])
                        
                        st.rerun()
                    except Exception as e:
                        status_container.update(label="⚠️ 오류 발생", state="error")
                        st.error(f"분석 오류: {e}")

            if st.session_state['analysis_result']:
                res = st.session_state['analysis_result']
                st.success("🎉 분석 완료! 오답노트에 저장되었습니다.")
                
                # 🔥 [UI 디자인 원복] expander 하나에 다 넣기
                with st.expander("📘 1타 강사의 상세 풀이 & 숏컷", expanded=True):
                    st.markdown(f"**핵심 개념:** {res.get('concept')}")
                    st.markdown("---")
                    st.markdown(res.get('solution').replace('\n', '  \n'))
                    st.markdown("---")
                    st.info(f"⚡ **숏컷:** {res.get('shortcut')}")
                    
                    if res.get('correction') and res.get('correction') != "첨삭 없음":
                        st.markdown("---")
                        st.markdown(f"**📝 첨삭 지도:**\n{res.get('correction').replace(chr(10), '  '+chr(10))}")

                with st.expander("📝 쌍둥이 문제 확인", expanded=True):
                    st.write(res.get('twin_problem'))
                    if st.button("정답 보기"):
                        st.write(res.get('twin_answer'))

                if st.session_state['solution_image']:
                    st.image(st.session_state['solution_image'], caption="오답노트 이미지", use_column_width=True)

                st.markdown("---")
                if st.button("🚨 고난도 심화 분석 요청 (Pro 모델)", type="secondary"):
                    status_container_pro = st.status("🧠 Pro 모델이 깊게 생각하는 중입니다... (약 15초)", expanded=True)
                    text_placeholder_pro = st.empty() 
                    
                    # 🔥 [Pro 프롬프트 유지] 
                    final_prompt_pro = f"""
                    당신은 대한민국 최고의 수능 수학 '1타 강사'입니다.
                    학생이 '고난도 심화 분석'을 요청했습니다. 
                    단순한 계산 나열이 아니라, **문제의 본질을 꿰뚫는 통찰(Insight)**을 보여주세요.

                    **[Deep Thinking Protocol: 심층 사고 단계]**
                    1. **[Geometry First]**: 문제를 보자마자 수식(Algebra)으로 덤비지 마세요. 
                       - **초등학교/중학교 도형(기하)의 성질** (닮음비, 합동, 원주각, 대칭성, 특수각 삼각형)로 풀 수 있는지 최우선으로 스캔하세요.
                       - "이 문제는 겉보기엔 미적분이지만, 실은 중2 닮음 문제입니다"와 같은 통찰을 보여주세요.
                    2. **[Dark Skills]**: 최상위권들만 아는 **'실전 스킬(Dark Skills)'**을 적극적으로 적용하세요.
                       - 예: 3/4차함수 비율 관계, 로피탈, 테일러 급수 근사(sin x ≈ x), 신발끈 공식, N축 스킬, 파푸스-굴딘 등.
                    3. **[Integrated Thinking]**: 초1부터 고3까지의 모든 교육과정을 연결하여 가장 빠르고 직관적인 길을 제시하세요.

                    **[핵심 지침]**
                    1. **절대 JSON 포맷을 사용하지 마세요.**
                    2. 아래의 구분자(===...===)를 사용하여 내용을 명확히 나누세요.
                    3. **모든 수식은 LaTeX($$)를 사용하세요.**

                    **[출력 형식]**
                    ===CONCEPT===
                    (심화 개념 및 출제 의도)
                    ===HINT===
                    (결정적 힌트: 도형의 보조선이나 특수 스킬 언급)
                    ===SOLUTION===
                    (논리적이고 치밀한 정석 풀이)
                    ===SHORTCUT===
                    (고난도 문제용 실전 숏컷: 암흑 스킬 및 기하학적 해석 포함)
                    ===CORRECTION===
                    (학생의 사고 과정에 대한 깊이 있는 피드백 및 함정 경고)
                    """
                    try:
                        res_text_pro, _ = generate_content_with_fallback(final_prompt_pro, st.session_state['gemini_image'], mode="pro", status_container=status_container_pro, text_placeholder=text_placeholder_pro)
                        
                        text_placeholder_pro.empty()
                        status_container_pro.update(label="✅ Pro 분석 완료!", state="complete", expanded=False)
                        
                        data_pro = parse_response_to_dict(res_text_pro)
                        data_pro['my_self_note'] = st.session_state['self_note']
                        
                        data_pro['twin_problem'] = st.session_state['analysis_result'].get('twin_problem')
                        data_pro['twin_answer'] = st.session_state['analysis_result'].get('twin_answer')

                        st.session_state['analysis_result'] = data_pro
                        
                        if st.session_state['saved_timestamp']:
                            overwrite_result_in_sheet(
                                st.session_state['user_name'], 
                                st.session_state['saved_timestamp'], 
                                data_pro
                            )
                        st.toast("Pro 분석으로 업데이트되었습니다!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Pro 분석 오류: {e}")

elif menu == "📒 내 오답 노트":
    st.markdown("""
    <div class="mb-6">
        <h1 class="text-2xl font-bold text-[#111418]">내 오답 노트 리스트</h1>
    </div>
    """, unsafe_allow_html=True)
    
    df = load_user_results(st.session_state['user_name'])
    
    if not df.empty:
        my_notes = df[df['이름'] == st.session_state['user_name']].sort_values(by='날짜', ascending=False)
        
        for index, row in my_notes.iterrows():
            with st.expander(f"📅 {row.get('날짜')} | {row.get('과목')} | {row.get('단원')}"):
                col_img, col_txt = st.columns([1, 2])
                with col_img:
                    if row.get('링크') and row.get('링크') != "이미지_없음":
                        st.image(row.get('링크'), use_column_width=True)
                    else: st.info("이미지 없음")
                
                with col_txt:
                    raw_content = row.get('내용')
                    content_json = None
                    
                    try:
                        content_json = ast.literal_eval(raw_content)
                    except:
                        try:
                            fixed_content = raw_content.replace("\\", "\\\\")
                            content_json = ast.literal_eval(fixed_content)
                        except:
                            st.warning("⚠️ 데이터 형식이 복잡하여 원본을 표시합니다.")
                            st.text(raw_content)

                    if content_json:
                        if 'my_self_note' in content_json and content_json['my_self_note']:
                            st.markdown(f"""
                            <div class="bg-orange-50 p-3 rounded-lg border border-orange-200 mb-3">
                                <span class="font-bold text-[#f97316]">✍️ 나의 정리:</span><br>
                                {content_json['my_self_note']}
                            </div>
                            """, unsafe_allow_html=True)
                        
                        st.markdown(f"**📘 개념:** {content_json.get('concept')}")
                        st.markdown("**📝 풀이:**")
                        sol_clean = content_json.get('solution', '').replace('\n', '  \n')
                        st.markdown(sol_clean)
                        st.info(f"⚡ 숏컷: {content_json.get('shortcut')}")
                        
                        if content_json.get('correction') and content_json.get('correction') != "첨삭 없음":
                            st.markdown("---")
                            st.markdown(f"**📝 첨삭 지도:**\n{content_json.get('correction').replace(chr(10), '  '+chr(10))}")

                        if 'chat_history' in content_json and content_json['chat_history']:
                            st.markdown("---")
                            if st.checkbox("💬 튜터링 대화 기록 보기", key=f"chat_view_{index}"):
                                for msg in content_json['chat_history']:
                                    role = "🤖 선생님" if msg['role'] == 'ai' else "🧑‍🎓 나"
                                    st.markdown(f"**{role}:** {msg['content']}")

                        if content_json.get('twin_problem'):
                            st.divider()
                            st.markdown("**📝 쌍둥이 문제**")
                            st.markdown(content_json.get('twin_problem').replace('\n', '  \n'))
                            if st.checkbox("정답 보기", key=f"twin_ans_{index}"):
                                st.markdown(content_json.get('twin_answer').replace('\n', '  \n'))

                if st.button("✅ 오늘 복습 완료", key=f"rev_{index}"):
                    if increment_review_count(row.get('날짜'), row.get('이름')):
                        st.toast("복습 횟수가 증가했습니다!")
                        time.sleep(1)
                        st.rerun()
    else: st.info("아직 저장된 오답 노트가 없습니다.")
