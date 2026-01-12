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
import random 
import ast 

# ----------------------------------------------------------
# [1] 기본 설정 & 디자인 주입 (HTML/Tailwind)
# ----------------------------------------------------------
st.set_page_config(page_title="MathAI Pro: Tutor Mode", page_icon="🏫", layout="wide")

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
        
        /* 채팅 메시지 스타일 */
        .stChatMessage { background-color: white; border-radius: 10px; padding: 10px; border: 1px solid #eee; }
        .stChatMessage[data-testid="user-message"] { background-color: #fff7ed; border-color: #fdba74; }
    </style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# [2] 유틸리티 함수 & 설정
# ----------------------------------------------------------

# 키 13개 자동 로드 로직
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

# 용도별 모델 분리 (하이브리드 전략)
FLASH_MODELS = [
    "gemini-3-flash-preview",    
    "gemini-2.5-flash",          
    "gemini-2.0-flash"           
]

PRO_MODELS = [
    "gemini-3-pro-preview",      
    "gemini-2.5-pro",            
    "deep-research-pro-preview-12-2025" 
]

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

def save_result_to_sheet(student_name, subject, unit, summary, link):
    client = get_sheet_client()
    if not client: return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([now, student_name, subject, unit, summary, link, "", 0])
        st.toast("✅ 학습 기록 저장 완료!", icon="💾")
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

# 스마트 하이브리드 AI 호출 함수
def generate_content_with_fallback(prompt, image=None, mode="chat"):
    last_error = None
    target_models = FLASH_MODELS if mode == "chat" else PRO_MODELS
    key_indices = list(range(len(API_KEYS)))
    random.shuffle(key_indices)

    for model_name in target_models:
        for key_idx in key_indices:
            current_key = API_KEYS[key_idx]
            try:
                genai.configure(api_key=current_key)
                model = genai.GenerativeModel(model_name)
                if image: response = model.generate_content([prompt, image])
                else: response = model.generate_content(prompt)
                return response.text, f"✅ {model_name}"
            except Exception as e:
                last_error = e
                time.sleep(0.5) 
                continue
    
    if mode == "final":
        for model_name in FLASH_MODELS:
            for key_idx in key_indices:
                current_key = API_KEYS[key_idx]
                try:
                    genai.configure(api_key=current_key)
                    model = genai.GenerativeModel(model_name)
                    if image: response = model.generate_content([prompt, image])
                    else: response = model.generate_content(prompt)
                    return response.text, f"⚠️ {model_name} (Backup)"
                except: continue

    raise last_error

def sanitize_json(text):
    pattern = r'\\(?![\\/bfnrtu"])' 
    return re.sub(pattern, r'\\\\', text)

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
    st.markdown(f"### 👋 반가워요, {st.session_state['user_name']}님!")
    menu = st.radio("학습 메뉴", ["📸 문제 풀기", "📒 내 오답 노트"])
    
    if st.button("🔄 초기화 (새 문제)"):
        st.session_state['chat_active'] = False
        st.session_state['chat_messages'] = []
        st.session_state['analysis_result'] = None
        st.session_state['gemini_image'] = None
        st.session_state['self_note'] = ""
        st.rerun()
        
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.rerun()

if menu == "📸 문제 풀기":
    col_spacer1, col_main, col_spacer2 = st.columns([0.5, 10, 0.5])
    
    with col_main:
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
                    st.image(image, caption="선택한 문제", use_container_width=True)
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    if st.button("💬 AI 튜터링 시작", type="primary"):
                        st.session_state['gemini_image'] = resize_image(image)
                        st.session_state['selected_subject'] = selected_subject
                        st.session_state['chat_active'] = True
                        st.session_state['chat_messages'] = [
                            {"role": "ai", "content": "문제를 확인했어! 🤔\n\n바로 답을 알려주기보다는 같이 풀어보면 실력이 더 늘 거야.\n\n이 문제에서 **어떤 부분이 가장 헷갈리거나 막혔니?** 편하게 말해봐!"}
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
            # ------------------------------------------------
            # [Step 2] 튜터링 & 결과 화면 (UI 위치 변경됨)
            # ------------------------------------------------
            chat_col_left, chat_col_right = st.columns([1, 1.2], gap="medium")
            
            # 🔥 [왼쪽 컬럼] 이미지 + 채팅 (학습 과정)
            with chat_col_left:
                st.markdown('<div class="math-card">', unsafe_allow_html=True)
                st.markdown('<h3 class="font-bold mb-2 text-slate-700">📄 문제 & 튜터링</h3>', unsafe_allow_html=True)
                if st.session_state['gemini_image']:
                    st.image(st.session_state['gemini_image'], use_container_width=True)
                
                st.markdown("---")
                
                # 채팅창 (왼쪽 하단에 배치)
                st.markdown('<div class="h-[500px] overflow-y-auto flex flex-col relative">', unsafe_allow_html=True)
                for msg in st.session_state['chat_messages']:
                    if msg['role'] == 'ai':
                        with st.chat_message("assistant", avatar="🤖"):
                            st.write(msg['content'])
                    else:
                        with st.chat_message("user", avatar="🧑‍🎓"):
                            st.write(msg['content'])

                if not st.session_state['analysis_result']:
                    if prompt := st.chat_input("질문을 입력하세요 (예: 여기서 어떻게 식을 세워?)"):
                        st.session_state['chat_messages'].append({"role": "user", "content": prompt})
                        st.rerun()

                if st.session_state['chat_messages'] and st.session_state['chat_messages'][-1]['role'] == 'user' and not st.session_state['analysis_result']:
                    with st.spinner("선생님이 답변을 생각 중입니다..."):
                        try:
                            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state['chat_messages']])
                            tutor_prompt = f"""
                            당신은 친절하지만 핵심을 찌르는 수학 '튜터'입니다. 과목: {st.session_state['selected_subject']}
                            [대화 내역] {history_text}
                            [지시사항]
                            1. 정답을 바로 주지 말고 힌트나 역질문을 하세요.
                            2. 수식은 LaTeX($$)를 사용하세요. (예: $x^2$)
                            3. 짧고 명확하게(3문장 이내) 답변하세요.
                            """
                            response_text, _ = generate_content_with_fallback(tutor_prompt, st.session_state['gemini_image'], mode="chat")
                            st.session_state['chat_messages'].append({"role": "ai", "content": response_text})
                            st.rerun()
                        except Exception as e:
                            st.error(f"채팅 오류: {e}")
                st.markdown('</div></div>', unsafe_allow_html=True)

            # 🔥 [오른쪽 컬럼] 나의 정리 + 최종 결과 (학습 결과)
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
                        with st.spinner("최종 리포트를 생성하고 오답노트에 저장 중입니다..."):
                            final_prompt = f"""
                            당신은 대한민국 최고의 수능 수학 '1타 강사'입니다. (과목:{st.session_state['selected_subject']})
                            이미지를 분석하여 JSON 형식으로 결과를 출력하세요.

                            **[학생의 Self-Note 내용]**
                            {st.session_state['self_note']}
                            (이 내용도 참고하여 첨삭이나 총평에 반영해주세요.)

                            **[핵심 지침: 1타 강사의 숏컷(Shortcut) 우선 적용]**
                            문제를 풀 때 다음의 '실전 스킬'이 적용 가능한지 최우선으로 검토하고, 가능하다면 **[2] 숏컷 풀이**에 반드시 상세히 포함하세요.
                            1. **[다항함수]** 3차/4차함수 비율 관계(2:1, 3:1 법칙), 넓이 공식(1/6, 1/12 공식), 높이차 공식.
                            2. **[수열]** 등차수열 합의 기하학적 해석(원점 지나는 2차함수), 등비수열의 덩어리 합 법칙, 등차중항(평균×개수).
                            3. **[미분/적분]** 이차함수 두 점 사이 기울기 = 중점의 미분계수, 0 근처 근사(sin x ≈ x), 변곡접선 영역 구분.
                            4. **[삼각/기하]** 단위원기반 해석, 사인법칙(지름의 지배), 코사인법칙(피타고라스 보정).

                            **[필수 지침]**
                            1. **무조건 JSON 포맷**만 출력하세요. 마크다운(```json)이나 사족을 달지 마세요.
                            2. **[매우 중요] 모든 수식은 LaTeX 포맷($...$)을 사용하세요.** (예: x^2 대신 $x^2$, sqrt(x) 대신 $\sqrt{{x}}$)
                            3. 숏컷(Shortcut)을 최우선으로 적용하여 풀이를 작성하세요.

                            **[출력해야 할 JSON 구조]**
                            {{
                                "formula": "인식된 수식 (LaTeX)",
                                "concept": "핵심 개념 (예: 3차함수 비율 관계)",
                                "hint_for_image": "이미지용 3줄 힌트 (LaTeX 금지, 텍스트만)",
                                "solution": "상세 풀이 (정석 풀이, 단계별 논리, 수식은 $...$ 사용)",
                                "shortcut": "1타 강사의 숏컷 풀이 (직관적, 빠른 풀이, 수식은 $...$ 사용)",
                                "correction": "학생의 풀이 또는 Self-Note에 대한 피드백/첨삭",
                                "twin_problem": "쌍둥이 문제 (LaTeX)",
                                "twin_answer": "쌍둥이 문제 정답 및 해설 (LaTeX)"
                            }}
                            """
                            try:
                                res_text, _ = generate_content_with_fallback(final_prompt, st.session_state['gemini_image'], mode="final")
                                clean_json = sanitize_json(res_text.replace("```json", "").replace("```", "").strip())
                                match = re.search(r'\{[\s\S]*\}', clean_json)
                                if match: clean_json = match.group(0)
                                
                                data = json.loads(clean_json)
                                data['my_self_note'] = st.session_state['self_note']
                                st.session_state['analysis_result'] = data
                                
                                st.session_state['solution_image'] = create_solution_image(
                                    st.session_state['gemini_image'], data.get('hint_for_image', '힌트 없음')
                                )
                                img_byte_arr = io.BytesIO()
                                st.session_state['solution_image'].save(img_byte_arr, format='JPEG', quality=90)
                                link = upload_to_imgbb(img_byte_arr.getvalue()) or "이미지_없음"
                                
                                save_result_to_sheet(
                                    st.session_state['user_name'], 
                                    st.session_state['selected_subject'], 
                                    data.get('concept'), 
                                    str(data), 
                                    link
                                )
                                st.rerun()
                            except Exception as e:
                                st.error(f"분석 오류: {e}")

                if st.session_state['analysis_result']:
                    res = st.session_state['analysis_result']
                    st.success("🎉 분석 완료! 오답노트에 저장되었습니다.")
                    with st.expander("📘 1타 강사의 상세 풀이 & 숏컷", expanded=True):
                        st.markdown(f"**핵심 개념:** {res.get('concept')}")
                        st.markdown("---")
                        st.markdown(res.get('solution').replace('\n', '  \n'))
                        st.markdown("---")
                        st.info(f"⚡ **숏컷:** {res.get('shortcut')}")
                    with st.expander("📝 쌍둥이 문제 확인"):
                        st.write(res.get('twin_problem'))
                        if st.button("정답 보기"):
                            st.write(res.get('twin_answer'))
                    if st.session_state['solution_image']:
                        st.image(st.session_state['solution_image'], caption="오답노트 이미지", use_container_width=True)

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
                    else: st.info("이미지 없음")
                with col_txt:
                    try:
                        content_json = ast.literal_eval(row.get('내용'))
                        
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
                        if content_json.get('twin_problem'):
                            st.divider()
                            st.markdown("**📝 쌍둥이 문제**")
                            st.markdown(content_json.get('twin_problem').replace('\n', '  \n'))
                            with st.expander("정답 보기"):
                                st.markdown(content_json.get('twin_answer').replace('\n', '  \n'))
                    except: 
                        st.warning("데이터 형식이 오래되었거나 손상되었습니다.")
                        st.write(row.get('내용'))
                if st.button("✅ 오늘 복습 완료", key=f"rev_{index}"):
                    if increment_review_count(row.get('날짜'), row.get('이름')):
                        st.toast("복습 횟수가 증가했습니다!")
                        time.sleep(1)
                        st.rerun()
    else: st.info("아직 저장된 오답 노트가 없습니다.")
