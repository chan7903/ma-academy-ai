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
import re # 정규표현식 (코드 분리용)
import matplotlib.pyplot as plt # 그래프 그리기
import numpy as np # 수학 연산

# ----------------------------------------------------------
# [1] 기본 설정
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫", layout="centered")

# 한글 폰트 설정 (깨짐 방지용 - 영문 표기 우선)
plt.rcParams['font.family'] = 'sans-serif' 
plt.rcParams['axes.unicode_minus'] = False

MODEL_NAME = "gemini-2.5-flash"
SHEET_ID = "1zJ2rs68pSE9Ntesg1kfqlI7G22ovfxX8Fb7v7HgxzuQ"

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    IMGBB_API_KEY = st.secrets["IMGBB_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except:
    st.error("설정 오류: Secrets에 키가 없습니다.")
    st.stop()

# ----------------------------------------------------------
# [2] 구글 시트 연결
# ----------------------------------------------------------
@st.cache_resource
def get_sheet_client():
    try:
        secrets = st.secrets["gcp_service_account"]
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(secrets, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        return None

# ----------------------------------------------------------
# [3] ImgBB 업로드 함수
# ----------------------------------------------------------
def upload_to_imgbb(image_bytes):
    url = "https://api.imgbb.com/1/upload"
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "key": IMGBB_API_KEY,
        "image": encoded_image,
    }
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            return response.json()['data']['url']
        else:
            return None
    except Exception as e:
        return None

# ----------------------------------------------------------
# [4] 데이터 처리 (저장 및 복습 카운트)
# ----------------------------------------------------------
def save_result_to_sheet(student_name, grade, unit, summary, link):
    client = get_sheet_client()
    if not client: return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([now, student_name, grade, unit, summary, link, "", 0])
        st.toast("✅ 오답노트 저장 완료!", icon="💾")
    except Exception as e:
        st.error(f"저장 실패: {e}")

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

# ----------------------------------------------------------
# [NEW] 텍스트와 코드를 분리하고 실행하는 함수들
# ----------------------------------------------------------
def parse_and_separate_code(text):
    """
    AI 응답 텍스트에서 ```python ... ``` 블록을 찾아내어 분리합니다.
    Returns: (cleaned_text, code_str)
    """
    pattern = r"```python(.*?)```"
    match = re.search(pattern, text, re.DOTALL)
    
    code_str = None
    cleaned_text = text
    
    if match:
        code_str = match.group(1)
        # 텍스트에서는 코드 블록을 제거함 (화면에 안 보이게)
        cleaned_text = re.sub(pattern, "", text, flags=re.DOTALL).strip()
        
    return cleaned_text, code_str

def exec_code_direct(code_str):
    """추출된 파이썬 코드를 실행하여 그래프를 그립니다."""
    if not code_str: return
    try:
        local_vars = {'plt': plt, 'np': np}
        plt.figure(figsize=(6, 4)) 
        exec(code_str, globals(), local_vars)
        st.pyplot(plt.gcf()) 
        plt.clf() 
    except Exception as e:
        st.error(f"그래프 생성 오류: {e}")

# ----------------------------------------------------------
# [5] 로그인
# ----------------------------------------------------------
if 'is_logged_in' not in st.session_state:
    st.session_state['is_logged_in'] = False
    st.session_state['user_name'] = None
if 'analysis_result' not in st.session_state:
    st.session_state['analysis_result'] = None
if 'gemini_image' not in st.session_state:
    st.session_state['gemini_image'] = None

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
# [6] 메인 화면
# ----------------------------------------------------------
with st.sidebar:
    st.success(f"👋 {st.session_state['user_name']} 학생")
    menu = st.radio("메뉴 선택", ["📸 문제 풀기", "📒 내 오답 노트"])
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.session_state['analysis_result'] = None
        st.rerun()

# --- [메뉴 1] 문제 풀기 ---
if menu == "📸 문제 풀기":
    with st.sidebar:
        st.markdown("---")
        student_grade = st.selectbox("학년", ["초4", "초5", "초6", "중1", "중2", "중3", "고1", "고2", "고3"])
        if any(x in student_grade for x in ["초", "중1", "중2"]):
            tone = "친절하고 상세하게, 핵심은 정확히"
        else:
            tone = "대치동 1타 강사처럼 엄격하고 논리정연하게"

    st.markdown("### 🏫 MA학원 AI 오답 도우미")

    tab1, tab2 = st.tabs(["📸 카메라", "📂 갤러리"])
    img_file = None
    with tab1:
        cam = st.camera_input("촬영")
        if cam: img_file = cam
    with tab2:
        up = st.file_uploader("파일 선택", type=['jpg', 'png'])
        if up: img_file = up

    if img_file:
        img_bytes = img_file.getvalue()
        image_for_view = Image.open(io.BytesIO(img_bytes))
        st.image(image_for_view, caption="선택된 문제", width=400)

        if st.button("🔍 1타 강사 분석 시작", type="primary"):
            st.session_state['gemini_image'] = Image.open(io.BytesIO(img_bytes))
            
            link = "이미지_없음"
            with st.spinner("이미지 링크 생성 중..."):
                uploaded_link = upload_to_imgbb(img_bytes)
                if uploaded_link: link = uploaded_link

            with st.spinner(f"AI 선생님({MODEL_NAME})이 분석 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    
                    # 🔥 [강화된 프롬프트]
                    prompt = f"""
                    당신은 대치동 20년 경력 수학 강사입니다. 학년:{student_grade}, 말투:{tone}
                    
                    [지시사항]
                    1. 첫 줄: [단원: 단원명]
                    2. 풀이: 꼼꼼하고 가독성 좋게 작성.
                    3. **시각화 필수:** - 문제 상황을 설명하는 그림이나 그래프가 필요하면 **반드시 Python Code (Matplotlib)**로 작성할 것.
                       - 텍스트로 된 그림(ASCII Art)이나 문자표 도형은 **절대 사용 금지**.
                       - 코드는 ```python ... ``` 블록 안에 넣을 것.
                    4. 쌍둥이 문제: 1문제 출제. **정답과 해설은 맨 뒤에 ===해설=== 구분선 넣고 작성.**
                    """
                    
                    response = model.generate_content([prompt, st.session_state['gemini_image']])
                    st.session_state['analysis_result'] = response.text
                    
                    unit_name = "미분류"
                    if "[단원:" in response.text:
                        try: unit_name = response.text.split("[단원:")[1].split("]")[0].strip()
                        except: pass
                    
                    save_result_to_sheet(
                        st.session_state['user_name'], student_grade, unit_name, 
                        response.text, link
                    )
                    
                except Exception as e:
                    st.error(f"분석 오류: {e}")

    # --- [결과 화면 출력 로직 수정됨] ---
    if st.session_state['analysis_result']:
        st.markdown("---")
        full_text = st.session_state['analysis_result']
        parts = full_text.split("===해설===")
        
        # 1. 텍스트와 코드 분리
        cleaned_text, graph_code = parse_and_separate_code(parts[0])
        
        with st.container(border=True):
            st.markdown("### 💡 선생님의 분석")
            
            # 🔥 [순서 변경] 그래프가 있으면 먼저 그리기! (코드는 안 보임)
            if graph_code:
                st.markdown("#### 📊 AI 자동 생성 그래프")
                with st.spinner("그래프 그리는 중..."):
                    exec_code_direct(graph_code)
            
            # 🔥 그 다음에 텍스트 설명 출력 (코드가 제거된 텍스트)
            st.write(cleaned_text)
        
        # 2. 정답 및 해설
        if len(parts) > 1:
            with st.expander("🔐 정답 및 해설 보기 (클릭)"):
                st.write(parts[1])
        
        # 3. 쌍둥이 문제 추가 생성
        if st.button("🔄 쌍둥이 문제 추가 생성"):
            with st.spinner("비슷한 문제 만드는 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    # 🔥 [쌍둥이 문제 프롬프트도 강화]
                    extra_prompt = f"""
                    위 문제와 비슷한 쌍둥이 문제를 1개 더 만들어줘. 
                    학년:{student_grade}. 정답은 맨 뒤에 ===해설=== 구분선 뒤에 적어.
                    **중요:** 이 문제에 필요한 그래프나 도형이 있다면, **반드시 Python(Matplotlib) 코드로 작성해서** 그려줘.
                    텍스트 그림(ASCII)은 절대 쓰지 마.
                    """
                    res = model.generate_content([extra_prompt, st.session_state['gemini_image']])
                    p = res.text.split("===해설===")
                    
                    # 추가 문제 내용 분리
                    extra_text, extra_code = parse_and_separate_code(p[0])
                    
                    with st.container(border=True):
                        st.markdown("#### ➕ 추가 문제")
                        
                        # 🔥 추가 문제도 그래프 먼저!
                        if extra_code:
                            st.caption("문제 이해를 돕기 위한 그래프입니다.")
                            exec_code_direct(extra_code)
                            
                        st.write(extra_text)
                    
                    if len(p) > 1:
                        with st.expander("🔐 정답 보기"):
                            st.write(p[1])
                except Exception as e:
                    st.error(f"오류: {e}")

# --- [메뉴 2] 오답 노트 ---
elif menu == "📒 내 오답 노트":
    st.markdown("### 📒 내 오답 노트 리스트")
    st.caption("틀린 문제를 다시 보고 '복습 완료' 버튼을 눌러보세요!")
    
    with st.spinner("데이터 불러오는 중..."):
        df = load_user_results(st.session_state['user_name'])
    
    if not df.empty and '이름' in df.columns:
        my_notes = df[df['이름'] == st.session_state['user_name']]
        
        if not my_notes.empty:
            if '날짜' in my_notes.columns:
                my_notes = my_notes.sort_values(by='날짜', ascending=False)
            
            for index, row in my_notes.iterrows():
                review_cnt = row.get('복습횟수')
                if review_cnt == '' or review_cnt is None: review_cnt = 0
                
                label = f"📅 {row.get('날짜', '')} | [{row.get('단원', '단원미상')}] | 🔁 복습 {review_cnt}회"
                
                with st.expander(label):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        with st.container(border=True):
                            content = row.get('내용', '내용 없음')
                            c_parts = str(content).split("===해설===")
                            
                            # 저장된 내용에서 코드/텍스트 분리
                            note_text, note_code = parse_and_separate_code(c_parts[0])
                            
                            # 🔥 오답노트에서도 그래프 먼저 보여주고, 코드는 숨김
                            if note_code:
                                if st.button(f"📊 그래프 보기 #{index}"):
                                    exec_code_direct(note_code)
                            
                            st.write(note_text)

                            if len(c_parts) > 1:
                                if st.button("정답 보기", key=f"ans_{index}"):
                                    st.info(c_parts[1])
                                    
                        if st.button("✅ 오늘 복습 완료!", key=f"rev_{index}"):
                            if increment_review_count(row.get('날짜'), row.get('이름')):
                                st.toast("복습 횟수 증가! 🎉")
                                import time
                                time.sleep(0.5)
                                st.rerun()
                    with col2:
                        img_link = row.get('링크')
                        if img_link and str(img_link).startswith('http'):
                            st.image(img_link, caption="원본 문제", use_container_width=True)
                        else:
                            st.caption("이미지 없음")
        else:
            st.info("저장된 오답노트가 없습니다.")
    else:
        st.warning("데이터 로딩 실패")
