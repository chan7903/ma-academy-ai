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
import re # 정규표현식
import matplotlib.pyplot as plt 
import numpy as np 

# ----------------------------------------------------------
# [1] 기본 설정
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫", layout="centered")

# 한글 폰트 설정 (영어 우선, 한글 깨짐 방지 노력)
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
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(secrets, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        return None

def upload_to_imgbb(image_bytes):
    url = "https://api.imgbb.com/1/upload"
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"key": IMGBB_API_KEY, "image": encoded_image}
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            return response.json()['data']['url']
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
# [NEW] 스마트 파싱 함수 (개념, 코드, 본문 분리)
# ----------------------------------------------------------
def parse_response_smart(text):
    """
    AI 응답을 3부분으로 분리합니다.
    1. 개념 파트 (<<<핵심>>> ... <<<핵심끝>>>)
    2. 파이썬 코드 (```python ... ```)
    3. 메인 풀이 텍스트 (나머지)
    """
    # 1. 코드 추출
    code_pattern = r"```python(.*?)```"
    code_match = re.search(code_pattern, text, re.DOTALL)
    code_str = code_match.group(1) if code_match else None
    
    # 텍스트에서 코드는 제거
    text_no_code = re.sub(code_pattern, "", text, flags=re.DOTALL).strip()
    
    # 2. 개념 추출
    concept_pattern = r"<<<핵심>>>(.*?)<<<핵심끝>>>"
    concept_match = re.search(concept_pattern, text_no_code, re.DOTALL)
    concept_str = concept_match.group(1).strip() if concept_match else None
    
    # 텍스트에서 개념 태그 부분 제거 (메인 풀이만 남김)
    main_text = re.sub(concept_pattern, "", text_no_code, flags=re.DOTALL).strip()
    
    return main_text, concept_str, code_str

def exec_code_direct(code_str):
    """파이썬 코드 실행 및 그래프 출력"""
    if not code_str: return
    try:
        local_vars = {'plt': plt, 'np': np}
        plt.figure(figsize=(6, 4)) # 그래프 사이즈
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
        
        # 미리보기
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
                    
                    # 🔥 [핵심 프롬프트 설계: Version B + 스마트 그래프]
                    prompt = f"""
                    당신은 대치동 20년 경력 수학 강사입니다. 학년:{student_grade}, 말투:{tone}
                    
                    [필수 출력 형식]
                    1. 첫 줄: [단원: 단원명]
                    
                    2. **핵심 개념 (숨김용):**
                       이 문제를 푸는 데 필요한 공식이나 개념을 반드시 <<<핵심>>> 과 <<<핵심끝>>> 태그 사이에 적어주세요.
                       예: <<<핵심>>> 삼각형의 내각의 이등분선 정리: AB:AC = BD:CD <<<핵심끝>>>
                    
                    3. **시각화 (Python Matplotlib Code):**
                       - 문제 상황을 정확히 반영한 그래프 코드를 작성하세요. (```python ... ``` 블록 사용)
                       - **[중요: 좌표축 규칙]**
                         (A) **기하(도형) 문제:** `plt.axis('off')`를 사용하여 좌표축과 눈금을 모두 지우세요. (흰 배경)
                         (B) **함수(그래프) 문제:** x축, y축, 격자(`grid`)를 표시하세요.
                       - **[중요: 색상 규칙]**
                         (A) **문제 원본 그림:** 검은색 실선 (`color='black', linestyle='-'`)
                         (B) **풀이 보조선/접선:** 빨간색 점선 (`color='red', linestyle='--'`) 또는 파란색 점선.
                         (C) 점이나 교점은 `marker='o'` 등으로 강조.
                    
                    4. **단계별 풀이 (메인):**
                       - 줄글을 피하고, **Step 1, Step 2**와 같이 번호를 매겨 구조화하세요.
                       - 수식 위주로 간결하게 작성하세요. (단순 계산 생략 가능)
                       - **그래프와 동기화:** 보조선을 설명할 때 **"그림의 빨간색 점선을 보면..."** 처럼 색상을 언급하세요.
                       
                    5. 쌍둥이 문제: 1문제 출제. **정답과 해설은 맨 뒤에 ===해설=== 구분선 넣고 작성.**
                    """
                    
                    response = model.generate_content([prompt, st.session_state['gemini_image']])
                    st.session_state['analysis_result'] = response.text
                    
                    # 시트에 저장
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

    # --- [결과 화면 출력] ---
    if st.session_state['analysis_result']:
        st.markdown("---")
        full_text = st.session_state['analysis_result']
        parts = full_text.split("===해설===")
        
        # 1. 스마트 파싱 (본문, 개념, 코드 분리)
        main_text, concept_text, graph_code = parse_response_smart(parts[0])
        
        with st.container(border=True):
            st.markdown("### 💡 선생님의 분석")
            
            # (1) 핵심 개념 (있으면 접이식으로 표시)
            if concept_text:
                with st.expander("📚 필요한 핵심 개념 & 공식 (클릭해서 보기)"):
                    st.info(concept_text)

            # (2) 그래프 (있으면 최상단에 표시)
            if graph_code:
                st.markdown("#### 📊 시각화 자료")
                with st.spinner("그래프 그리는 중..."):
                    exec_code_direct(graph_code)
            
            # (3) 메인 풀이 텍스트
            st.write(main_text)
        
        # 2. 정답 및 해설 (쌍둥이 문제 등)
        if len(parts) > 1:
            with st.expander("🔐 쌍둥이 문제 정답 및 해설 보기"):
                st.write(parts[1])
        
        # 3. 쌍둥이 문제 추가 생성
        if st.button("🔄 쌍둥이 문제 추가 생성"):
            with st.spinner("비슷한 문제 만드는 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    extra_prompt = f"""
                    위 문제와 비슷한 쌍둥이 문제를 1개 더 만들어줘. 
                    학년:{student_grade}. 정답은 맨 뒤에 ===해설=== 구분선 뒤에 적어.
                    **중요:** 이 문제에 필요한 그래프나 도형이 있다면, **반드시 Python(Matplotlib) 코드로 작성해서** 그려줘.
                    - 도형 문제면 좌표축 지우기 (`plt.axis('off')`)
                    - 문제 원본은 검은색, 보조선은 빨간색 점선으로 구분해서 그려줘.
                    텍스트 그림(ASCII)은 절대 쓰지 마.
                    """
                    res = model.generate_content([extra_prompt, st.session_state['gemini_image']])
                    p = res.text.split("===해설===")
                    
                    # 추가 문제도 파싱
                    ex_text, ex_con, ex_code = parse_response_smart(p[0])
                    
                    with st.container(border=True):
                        st.markdown("#### ➕ 추가 문제")
                        if ex_code: exec_code_direct(ex_code) # 그래프 먼저
                        st.write(ex_text) # 텍스트 나중에
                    
                    if len(p) > 1:
                        with st.expander("🔐 정답 보기"):
                            st.write(p[1])
                except Exception as e:
                    st.error(f"오류: {e}")

# --- [메뉴 2] 오답 노트 ---
elif menu == "📒 내 오답 노트":
    st.markdown("### 📒 내 오답 노트 리스트")
    
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
                            
                            # 오답노트 다시 볼 때도 똑같이 파싱
                            n_text, n_con, n_code = parse_response_smart(c_parts[0])
                            
                            # (1) 개념
                            if n_con:
                                with st.expander("📚 핵심 개념 다시보기"):
                                    st.info(n_con)
                            # (2) 그래프
                            if n_code:
                                if st.button(f"📊 그래프 보기 #{index}"):
                                    exec_code_direct(n_code)
                            # (3) 본문
                            st.write(n_text)

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
