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
import json
import re

# ----------------------------------------------------------
# [1] 기본 설정 & 디자인 주입 (HTML/Tailwind)
# ----------------------------------------------------------
st.set_page_config(page_title="MathAI Pro", page_icon="🏫", layout="wide")

# Tailwind CSS & 폰트 주입 (디자인의 핵심)
st.markdown("""
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined" rel="stylesheet" />
    
    <style>
        .stApp { background-color: #f6f7f8; font-family: 'Lexend', 'Noto Sans KR', sans-serif; }
        header {visibility: hidden;} 
        .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 100% !important; }
        
        /* 버튼 스타일링 */
        div.stButton > button {
            background-color: #f97316 !important; color: white !important;
            border: none !important; border-radius: 0.5rem !important;
            padding: 0.75rem 1rem !important; font-weight: 700 !important;
            width: 100%; transition: all 0.2s;
        }
        div.stButton > button:hover { background-color: #ea580c !important; transform: scale(0.98); }
        
        /* 카드 디자인 클래스 */
        .math-card {
            background-color: white; border-radius: 0.75rem;
            border: 1px solid #e5e7eb; box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
            padding: 1.5rem; margin-bottom: 1.5rem;
        }
    </style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# [2] 원장님 기존 유틸리티 함수 & 설정 (그대로 유지)
# ----------------------------------------------------------

# API 키 설정 (st.secrets 사용)
try:
    API_KEYS = [
        st.secrets["GOOGLE_API_KEY"],
        st.secrets.get("GOOGLE_API_KEY_2", st.secrets["GOOGLE_API_KEY"]),
        st.secrets.get("GOOGLE_API_KEY_3", st.secrets["GOOGLE_API_KEY"]),
        st.secrets.get("GOOGLE_API_KEY_4", st.secrets["GOOGLE_API_KEY"])
    ]
    IMGBB_API_KEY = st.secrets["IMGBB_API_KEY"]
except:
    st.error("설정 오류: st.secrets에 API 키가 없습니다.")
    st.stop()

MODELS_TO_TRY = ["gemini-2.5-pro",           # 1순위: 가장 똑똑함 (첨삭 감지 및 숏컷 분석 최강)
    "gemini-2.5-flash",         # 2순위: 속도와 정확도의 밸런스
    "gemini-3-flash-preview",   # 3순위: 차세대 엔진
    "gemini-2.0-flash-lite-001" # 4순위: 비상용 조교
]
SHEET_ID = "1zJ2rs68pSE9Ntesg1kfqlI7G22ovfxX8Fb7v7HgxzuQ"

if 'key_index' not in st.session_state:
    st.session_state['key_index'] = 0

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
        st.toast("학습 기록이 저장되었습니다!", icon="💾")
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

# 이미지 생성용 텍스트 정제
def clean_text_for_plot_safe(text):
    if not text: return ""
    text = text.replace(r'\iff', '⇔').replace(r'\implies', '⇒')
    text = text.replace(r'\le', '≤').replace(r'\ge', '≥')
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
                display_line = line.strip()[:45] + "..." if len(line.strip()) > 45 else line.strip()
                ax_note.text(0.05, y_pos, f"• {display_line}", fontsize=21, color='#333333', va='top', ha='left', transform=ax_note.transAxes, fontproperties=font_prop)
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

# AI 호출 함수 (JSON 출력을 위해 프롬프트 구조 변경)
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
# [3] 로그인 & 세션 상태 관리
# ----------------------------------------------------------
if 'is_logged_in' not in st.session_state: st.session_state['is_logged_in'] = False
if 'analysis_result' not in st.session_state: st.session_state['analysis_result'] = None
if 'gemini_image' not in st.session_state: st.session_state['gemini_image'] = None
if 'solution_image' not in st.session_state: st.session_state['solution_image'] = None

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
                df['pw'] = df['pw'].astype(str)
                user_data = df[df['id'] == user_id]
                if not user_data.empty and user_data.iloc[0]['pw'] == user_pw:
                    st.session_state['is_logged_in'] = True
                    st.session_state['user_name'] = user_data.iloc[0]['name']
                    st.rerun()
                else: st.error("정보가 일치하지 않습니다.")
            else: st.error("데이터베이스 연결 실패")
        st.markdown('</div>', unsafe_allow_html=True)

if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

# ----------------------------------------------------------
# [4] 메인 UI (헤더 & 사이드바)
# ----------------------------------------------------------

# 커스텀 헤더 (HTML)
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
    st.markdown(f"### 👋 반가워요, {st.session_state['user_name']}님!")
    menu = st.radio("학습 메뉴", ["📸 문제 풀기", "📒 내 오답 노트"])
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.rerun()

# ----------------------------------------------------------
# [5] 기능 구현: 문제 풀기 모드
# ----------------------------------------------------------
if menu == "📸 문제 풀기":
    col_spacer1, col_main, col_spacer2 = st.columns([0.5, 10, 0.5])
    
    with col_main:
        # 타이틀
        st.markdown("""
        <div class="mb-6">
            <h1 class="text-2xl font-bold text-[#111418]">새 문제 분석</h1>
            <p class="text-slate-500 text-sm">AI 1타 강사가 풀이와 숏컷, 그리고 첨삭까지 제공합니다.</p>
        </div>
        """, unsafe_allow_html=True)

        # 2단 레이아웃
        left_col, right_col = st.columns([1, 1.2], gap="medium")

        # [왼쪽] 입력 카드
        with left_col:
            st.markdown('<div class="math-card h-full">', unsafe_allow_html=True)
            st.markdown('<h3 class="font-bold mb-4 text-slate-700">📤 문제 업로드</h3>', unsafe_allow_html=True)
            
            # 과목 선택
            subject_options = ["선택안함", "초등 수학", "중등 수학", "고등 공통수학", "수I", "수II", "미적분", "확통", "기하"]
            selected_subject = st.selectbox("과목/단원", subject_options, label_visibility="collapsed")
            
            # 파일 업로드
            tab1, tab2 = st.tabs(["파일 선택", "카메라"])
            img_file = None
            with tab1:
                img_file = st.file_uploader("이미지", type=['jpg', 'png'], label_visibility="collapsed")
            with tab2:
                cam = st.camera_input("촬영", label_visibility="collapsed")
                if cam: img_file = cam

            # 분석 버튼 및 로직
            if img_file and selected_subject != "선택안함":
                # 이미지 미리보기
                image = Image.open(img_file)
                if image.mode in ("RGBA", "P"): image = image.convert("RGB")
                st.image(image, caption="선택한 문제", use_container_width=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                
                if st.button("✨ AI 분석 시작", type="primary"):
                    with st.spinner("AI 선생님이 문제를 분석 중입니다..."):
                        try:
                            # 1. 이미지 리사이징
                            processed_img = resize_image(image)
                            st.session_state['gemini_image'] = processed_img
                            
                            # 2. JSON 출력을 위한 프롬프트 (디자인에 데이터 꽂기 위함)
                            prompt = f"""
                            당신은 대치동 1타 수학 강사입니다. 과목:{selected_subject}
                            이 이미지를 분석하여 다음 정보를 반드시 **JSON 형식**으로만 출력하세요.
                            
                            {{
                                "formula": "이미지 속 수식 (LaTeX 말고 일반 텍스트로 표현)",
                                "concept": "핵심 수학 개념 (단원명 포함)",
                                "solution": "단계별 정석 풀이 (줄바꿈은 \\n 사용, 논리적 흐름 중시)",
                                "shortcut": "빠르게 푸는 팁이나 공식 (없으면 '기본 개념 충실히')",
                                "correction": "학생의 풀이 흔적이 있다면 틀린 이유와 조언 (없으면 '풀이 흔적 없음')",
                                "hint_for_image": "오답노트 이미지 생성용 짧은 힌트 3줄"
                            }}
                            
                            응답은 오직 JSON 데이터만 포함해야 합니다. 마크다운 기호 없이 순수 JSON만 주세요.
                            """
                            
                            # 3. AI 호출
                            result_text, used_model = generate_content_with_fallback(prompt, processed_img)
                            
                            # 4. JSON 파싱
                            try:
                                clean_json = result_text.replace("```json", "").replace("```", "").strip()
                                data = json.loads(clean_json)
                                st.session_state['analysis_result'] = data
                                
                                # 5. 오답노트용 이미지(Post-it) 생성
                                st.session_state['solution_image'] = create_solution_image(
                                    processed_img, data.get('hint_for_image', '힌트 없음')
                                )
                                
                                # 6. 시트 저장 (자동)
                                img_byte_arr = io.BytesIO()
                                st.session_state['solution_image'].save(img_byte_arr, format='JPEG', quality=90)
                                link = upload_to_imgbb(img_byte_arr.getvalue()) or "이미지_없음"
                                save_result_to_sheet(
                                    st.session_state['user_name'], 
                                    selected_subject, 
                                    data.get('concept'), 
                                    str(data),  # 전체 데이터를 JSON 문자열로 저장
                                    link
                                )
                                
                            except json.JSONDecodeError:
                                st.error("AI 응답을 처리하는 중 오류가 발생했습니다. (JSON 파싱 실패)")
                                st.write(result_text) # 디버깅용 원문 출력
                                
                        except Exception as e:
                            st.error(f"분석 중 오류 발생: {e}")
            
            st.markdown('</div>', unsafe_allow_html=True) # 카드 닫기

        # [오른쪽] 결과 카드
        with right_col:
            if st.session_state['analysis_result']:
                res = st.session_state['analysis_result']
                
                # 1. 수식 인식 카드
                st.markdown(f"""
                <div class="math-card">
                    <div class="flex items-center justify-between mb-2">
                        <h3 class="font-bold text-slate-800 flex items-center gap-2">
                            <span class="material-symbols-outlined text-[#f97316]">auto_awesome</span>
                            AI 인식 결과
                        </h3>
                        <span class="text-xs font-bold text-green-600 bg-green-100 px-2 py-1 rounded-full">분석 완료</span>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-4 flex items-center justify-center border border-gray-200">
                        <p class="text-xl font-serif italic text-slate-800">{res.get('formula', '수식 인식 불가')}</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # 2. 풀이 카드
                st.markdown(f"""
                <div class="math-card">
                    <h4 class="font-bold text-sm text-slate-500 mb-3 uppercase tracking-wider">상세 풀이</h4>
                    <div class="space-y-4 pl-4 border-l-2 border-gray-100">
                        <div>
                            <p class="font-bold text-sm text-slate-800 mb-1">📘 핵심 개념: {res.get('concept')}</p>
                            <div class="text-sm text-slate-600 leading-relaxed whitespace-pre-line">{res.get('solution')}</div>
                        </div>
                         <div class="mt-4">
                            <p class="font-bold text-sm text-[#f97316] mb-1">⚡ 1타 강사 숏컷</p>
                            <p class="text-sm text-slate-700 bg-orange-50 p-3 rounded-lg border border-orange-100">{res.get('shortcut')}</p>
                        </div>
                    </div>
                    <div class="mt-6 pt-4 border-t border-gray-100">
                        <p class="text-sm font-bold text-red-500 mb-2">🚩 첨삭 노트</p>
                        <p class="text-sm text-slate-600">{res.get('correction')}</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # 3. 생성된 이미지 카드
                if st.session_state['solution_image']:
                    st.markdown('<div class="math-card">', unsafe_allow_html=True)
                    st.write("🖼️ **오답 노트용 요약 이미지**")
                    st.image(st.session_state['solution_image'], use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                # 대기 화면
                st.markdown("""
                <div class="math-card flex flex-col items-center justify-center text-center h-[400px]">
                    <span class="material-symbols-outlined text-gray-300 text-[60px] mb-4">fact_check</span>
                    <h3 class="text-lg font-bold text-slate-700 mb-2">분석 대기 중</h3>
                    <p class="text-slate-500 text-sm">왼쪽에서 문제를 업로드하고<br>분석 버튼을 눌러주세요.</p>
                </div>
                """, unsafe_allow_html=True)

# ----------------------------------------------------------
# [6] 기능 구현: 내 오답 노트 (기존 로직 유지)
# ----------------------------------------------------------
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
                        st.image(row.get('링크'), use_container_width=True)
                    else:
                        st.info("이미지 없음")
                with col_txt:
                    try:
                        # 저장된 JSON 문자열을 파싱해서 보여주기
                        content_json = json.loads(row.get('내용').replace("'", "\""))
                        st.markdown(f"**풀이:** {content_json.get('solution')}")
                        st.info(f"⚡ 숏컷: {content_json.get('shortcut')}")
                    except:
                        # 예전 데이터(JSON 아님)일 경우 그냥 출력
                        st.write(row.get('내용'))
                
                if st.button("✅ 오늘 복습 완료", key=f"rev_{index}"):
                    if increment_review_count(row.get('날짜'), row.get('이름')):
                        st.toast("복습 횟수가 증가했습니다!")
                        time.sleep(1)
                        st.rerun()
    else:
        st.info("아직 저장된 오답 노트가 없습니다.")

