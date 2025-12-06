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
import re 
import matplotlib.pyplot as plt 
import numpy as np 
import cv2 # 이미지 처리 라이브러리 (OpenCV)

# ----------------------------------------------------------
# [1] 기본 설정
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫", layout="centered")

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
# [2] 구글 시트 및 유틸리티
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

def upload_to_imgbb(image_bytes):
    url = "https://api.imgbb.com/1/upload"
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"key": IMGBB_API_KEY, "image": encoded_image}
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200: return response.json()['data']['url']
        return None
    except: return None

def save_result_to_sheet(student_name, grade, unit, summary, link):
    client = get_sheet_client()
    if not client: return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([now, student_name, grade, unit, summary, link, "", 0])
        st.toast("✅ 오답노트 저장 완료!", icon="💾")
    except Exception as e: st.error(f"저장 실패: {e}")

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
# [NEW] 이미지 전처리 함수 (샤프 자국 지우기)
# ----------------------------------------------------------
def preprocess_image(image_bytes):
    """
    이미지를 받아 흑백으로 변환하고, 
    Adaptive Thresholding을 적용하여 연필 자국과 그림자를 제거합니다.
    """
    # 1. 바이트 -> OpenCV 이미지로 변환
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # 2. 흑백 변환 (GrayScale)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 3. 노이즈 제거 (블러링) - 점박이 노이즈 제거
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # 4. 적응형 이진화 (Adaptive Thresholding) 
    # - 조명이 불균일해도 글자만 잘 따내는 기술 (스캐너 앱 원리)
    # - 255: 흰색으로 만듦 / 11: 블록 사이즈 / 2: 상수(조절값)
    processed = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 11, 2
    )
    
    # 5. OpenCV 이미지 -> PIL 이미지로 다시 변환 (Streamlit/Gemini용)
    return Image.fromarray(processed)

# ----------------------------------------------------------
# [NEW] 스마트 파싱 함수
# ----------------------------------------------------------
def parse_response_smart(text):
    # 코드 추출
    code_pattern = r"```python(.*?)```"
    code_match = re.search(code_pattern, text, re.DOTALL)
    code_str = code_match.group(1) if code_match else None
    text_no_code = re.sub(code_pattern, "", text, flags=re.DOTALL).strip()
    
    # 개념 추출
    concept_pattern = r"<<<핵심>>>(.*?)<<<핵심끝>>>"
    concept_match = re.search(concept_pattern, text_no_code, re.DOTALL)
    concept_str = concept_match.group(1).strip() if concept_match else None
    main_text = re.sub(concept_pattern, "", text_no_code, flags=re.DOTALL).strip()
    
    # 잡다한 헤더 청소
    garbage_headers = ["핵심 개념 (숨김용):", "시각화 (Python Matplotlib Code):", 
                       "단계별 풀이 (메인):", "시각화:", "**시각화**", "**단계별 풀이**"]
    for header in garbage_headers:
        main_text = main_text.replace(header, "")
    
    main_text = re.sub(r"^\d+\.\s*$", "", main_text, flags=re.MULTILINE)
    return main_text.strip(), concept_str, code_str

def exec_code_direct(code_str):
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
# [5] 로그인 및 메인 로직
# ----------------------------------------------------------
if 'is_logged_in' not in st.session_state:
    st.session_state['is_logged_in'] = False
if 'analysis_result' not in st.session_state:
    st.session_state['analysis_result'] = None
if 'gemini_image' not in st.session_state:
    st.session_state['gemini_image'] = None

# (로그인 페이지 코드는 동일하여 생략, 위 코드와 그대로 연결됨)
def login_page():
    # ... (기존과 동일)
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

with st.sidebar:
    st.success(f"👋 {st.session_state['user_name']} 학생")
    menu = st.radio("메뉴 선택", ["📸 문제 풀기", "📒 내 오답 노트"])
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.rerun()

if menu == "📸 문제 풀기":
    with st.sidebar:
        st.markdown("---")
        student_grade = st.selectbox("학년", ["초4", "초5", "초6", "중1", "중2", "중3", "고1", "고2", "고3"])
        tone = "친절하고 상세하게" if any(x in student_grade for x in ["초", "중1", "중2"]) else "대치동 1타 강사처럼 엄격하게"

    st.markdown("### 🏫 MA학원 AI 오답 도우미")
    
    # 탭 구성
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
        
        # [화면 표시용] 원본 이미지
        st.image(Image.open(io.BytesIO(img_bytes)), caption="원본 사진", width=300)

        if st.button("🔍 1타 강사 분석 시작", type="primary"):
            
            # 🔥 [핵심] 여기서 전처리를 수행합니다!
            with st.spinner("이미지 스캔 중 (낙서 지우기)..."):
                # 전처리된 PIL 이미지 (샤프 자국 지워짐)
                clean_image = preprocess_image(img_bytes) 
                st.session_state['gemini_image'] = clean_image
                
                # 전처리된 이미지를 화면에 보여줌 (확인용)
                with st.expander("✨ 깨끗하게 변환된 이미지 보기"):
                    st.image(clean_image, caption="AI가 보는 이미지 (낙서 제거됨)")

            link = "이미지_없음"
            with st.spinner("이미지 링크 생성 중..."):
                uploaded_link = upload_to_imgbb(img_bytes) # 오답노트엔 원본 저장 (나중에 볼 땐 원본이 나음)
                if uploaded_link: link = uploaded_link

            with st.spinner(f"AI 선생님({MODEL_NAME})이 분석 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    
                    # 프롬프트: "흑백 이미지"를 준다는 것을 인지시킴
                    prompt = f"""
                    당신은 대치동 20년 경력 수학 강사입니다. 학년:{student_grade}, 말투:{tone}
                    
                    [상황]
                    이 이미지는 학생이 찍은 문제 사진을 **이진화(흑백 스캔) 처리**하여 손글씨와 낙서를 최대한 지운 상태입니다.
                    하지만 일부 지워지지 않은 자국이나 끊어진 글자가 있을 수 있습니다.
                    **수학적 문맥을 활용하여 끊어진 글자나 숫자를 올바르게 추론해서** 문제를 풀어주세요.
                    
                    [지시사항]
                    1. 첫 줄: [단원: 단원명]
                    2. **핵심 개념:** <<<핵심>>> 태그 안에 작성.
                    3. **시각화:** Python Matplotlib 코드 (```python ... ```). 
                       - 기하: `plt.axis('off')`, 함수: 축 표시.
                       - 원본 검은색, 보조선 빨간색 점선.
                    4. **단계별 풀이:** 바로 Step 1 시작.
                    5. 쌍둥이 문제: ===해설=== 뒤에 작성.
                    """
                    
                    response = model.generate_content([prompt, st.session_state['gemini_image']])
                    st.session_state['analysis_result'] = response.text
                    
                    # 시트 저장
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

    # 결과 화면 (기존과 동일)
    if st.session_state['analysis_result']:
        st.markdown("---")
        full_text = st.session_state['analysis_result']
        parts = full_text.split("===해설===")
        main_text, concept_text, graph_code = parse_response_smart(parts[0])
        
        with st.container(border=True):
            st.markdown("### 💡 선생님의 분석")
            if concept_text:
                with st.expander("📚 필요한 핵심 개념 & 공식"):
                    st.info(concept_text)
            if graph_code:
                st.markdown("#### 📊 AI 자동 생성 그래프")
                with st.spinner("그래프 그리는 중..."):
                    exec_code_direct(graph_code)
            st.write(main_text)
        
        if len(parts) > 1:
            with st.expander("🔐 쌍둥이 문제 정답 및 해설"):
                st.write(parts[1])
        
        if st.button("🔄 쌍둥이 문제 추가 생성"):
            with st.spinner("비슷한 문제 만드는 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    extra_prompt = f"""
                    위 문제와 비슷한 쌍둥이 문제를 1개 더. 학년:{student_grade}. 정답은 ===해설=== 뒤에.
                    그래프는 Python 코드로, 좌표축 처리 주의.
                    """
                    res = model.generate_content([extra_prompt, st.session_state['gemini_image']])
                    p = res.text.split("===해설===")
                    ex_text, ex_con, ex_code = parse_response_smart(p[0])
                    with st.container(border=True):
                        st.markdown("#### ➕ 추가 문제")
                        if ex_code: exec_code_direct(ex_code)
                        st.write(ex_text)
                    if len(p) > 1:
                        with st.expander("🔐 정답 보기"):
                            st.write(p[1])
                except Exception as e: st.error(f"오류: {e}")

# 오답노트 메뉴 (기존 코드 유지)
elif menu == "📒 내 오답 노트":
    # (오답노트 부분은 위쪽 코드 그대로 사용하시면 됩니다. 분량상 생략하지 않고 
    #  필요하시면 앞선 답변의 오답노트 부분과 똑같이 붙여넣으시면 됩니다.)
    st.markdown("### 📒 내 오답 노트 리스트")
    with st.spinner("데이터 불러오는 중..."):
        df = load_user_results(st.session_state['user_name'])
    if not df.empty and '이름' in df.columns:
        my_notes = df[df['이름'] == st.session_state['user_name']]
        if not my_notes.empty:
            if '날짜' in my_notes.columns: my_notes = my_notes.sort_values(by='날짜', ascending=False)
            for index, row in my_notes.iterrows():
                review_cnt = row.get('복습횟수', 0)
                if review_cnt == '': review_cnt = 0
                label = f"📅 {row.get('날짜', '')} | [{row.get('단원', '단원미상')}] | 🔁 복습 {review_cnt}회"
                with st.expander(label):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        with st.container(border=True):
                            content = row.get('내용', '내용 없음')
                            c_parts = str(content).split("===해설===")
                            n_text, n_con, n_code = parse_response_smart(c_parts[0])
                            if n_con: st.info(f"📚 핵심: {n_con}")
                            if n_code: 
                                if st.button(f"📊 그래프 보기 #{index}"): exec_code_direct(n_code)
                            st.write(n_text)
                            if len(c_parts) > 1:
                                if st.button("정답 보기", key=f"ans_{index}"): st.info(c_parts[1])
                        if st.button("✅ 오늘 복습 완료!", key=f"rev_{index}"):
                            if increment_review_count(row.get('날짜'), row.get('이름')):
                                st.toast("복습 횟수 증가!")
                                import time
                                time.sleep(0.5)
                                st.rerun()
                    with col2:
                        img_link = row.get('링크')
                        if img_link and str(img_link).startswith('http'):
                            st.image(img_link, caption="원본 문제", use_container_width=True)
                        else: st.caption("이미지 없음")
        else: st.info("저장된 오답노트가 없습니다.")
    else: st.warning("데이터 로딩 실패")
