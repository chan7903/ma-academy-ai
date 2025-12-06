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

# ----------------------------------------------------------
# [1] 기본 설정
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫", layout="centered")

plt.rcParams['font.family'] = 'sans-serif' 
plt.rcParams['axes.unicode_minus'] = False

MODEL_NAME = "gemini-2.5-flash"

# 🔥 [확인] 선생님의 진짜 시트 ID를 넣어주세요!
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

def save_result_to_sheet(student_name, curriculum, subject, summary, link):
    client = get_sheet_client()
    if not client: return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 저장 컬럼: [날짜, 이름, 교육과정, 과목, 내용, 링크, (공란), 복습횟수]
        sheet.append_row([now, student_name, curriculum, subject, summary, link, "", 0])
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
    if not client: 
        st.error("❌ 구글 인증 실패: Secrets 설정을 확인하세요.")
        return None
    try:
        sheet_file = client.open_by_key(SHEET_ID)
        sheet = sheet_file.worksheet("students")
        return pd.DataFrame(sheet.get_all_records())
    except Exception as e:
        st.error(f"❌ 접속 실패 상세 원인: {e}")
        return None

# ----------------------------------------------------------
# [3] 스마트 파싱 함수
# ----------------------------------------------------------
def parse_response_smart(text):
    code_pattern = r"```(?:python)?(.*?)```"
    code_match = re.search(code_pattern, text, re.DOTALL)
    code_str = code_match.group(1) if code_match else None
    
    text_no_code = re.sub(code_pattern, "", text, flags=re.DOTALL).strip()
    
    concept_pattern = r"<<<핵심>>>(.*?)<<<핵심끝>>>"
    concept_match = re.search(concept_pattern, text_no_code, re.DOTALL)
    concept_str = concept_match.group(1).strip() if concept_match else None
    
    main_text = re.sub(concept_pattern, "", text_no_code, flags=re.DOTALL).strip()
    
    garbage_headers = [
        "핵심 개념 (숨김용):", "시각화 (Python Matplotlib Code):", 
        "단계별 풀이 (메인):", "시각화:", "**시각화**", "**단계별 풀이**",
        "### 시각화", "### 단계별 풀이"
    ]
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
# [NEW] 과목별 상세 제약 조건 (2015 vs 2022 완벽 대응)
# ----------------------------------------------------------
def get_subject_constraints(curriculum, subject):
    base_msg = f"현재 교육과정은 '{curriculum}'이며, 과목은 '{subject}'입니다.\n"
    
    # [1] 2015 개정 교육과정 제약
    if "2015" in curriculum:
        if "수학 II" in subject:
            return base_msg + """
            [⚠️ 수학 II 제약조건 - 절대 엄수]
            1. '다항함수의 미분과 적분'만 사용 가능합니다.
            2. **금지:** 음함수/매개변수/합성함수 미분, 지수/로그/삼각함수 미분 절대 금지.
            3. 로피탈의 정리 사용 금지. 식을 변형하여 극한을 구하는 정석 풀이를 보여주세요.
            4. 도형 문제 등에서도 변수를 하나로 통일하여 다항함수로 유도하세요.
            """
        elif "미적분" in subject:
            return base_msg + "[미적분(선택) 가이드] 모든 미분법(초월함수, 합성함수 등)을 자유롭게 사용하여 최적의 풀이를 제시하세요."
        elif "기하" in subject:
            return base_msg + "[기하 가이드] 해석기하(좌표)보다는 유클리드 기하(닮음, 합동) 성질을 우선적으로 사용하여 풀이하세요."
    
    # [2] 2022 개정 교육과정 제약 (용어 변화 대응)
    elif "2022" in curriculum:
        if "미적분 I" in subject: # (구 수학 II와 유사)
            return base_msg + """
            [⚠️ 2022개정 '미적분 I' 제약조건 - 절대 엄수]
            1. 이 과목은 구 교육과정의 '수학 II'에 해당합니다. (다항함수의 미적분)
            2. **금지:** 수열의 극한, 초월함수(지수/로그/삼각) 미적분, 여러 가지 미분법 절대 금지.
            3. 오직 다항함수의 도함수와 정적분 개념만 사용하세요.
            """
        elif "미적분 II" in subject: # (구 미적분과 유사)
            return base_msg + "[2022개정 '미적분 II' 가이드] 모든 심화 미분법과 적분법을 자유롭게 사용하세요."
        elif "대수" in subject: # (구 수학 I과 유사)
            return base_msg + "[2022개정 '대수' 가이드] 지수, 로그, 삼각함수, 수열의 기본 개념을 활용하되 미분은 사용하지 마세요."
            
    # [3] 공통/기타
    return base_msg + "[일반 가이드] 학생의 학습 수준(초/중/고)에 맞는 용어와 공식을 사용하세요."

# ----------------------------------------------------------
# [5] 로그인 및 메인
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
            else: 
                if df is None: st.error("접속 오류 발생")
                else: st.error("학생 데이터 없음")

if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

with st.sidebar:
    st.success(f"👋 {st.session_state['user_name']} 학생")
    menu = st.radio("메뉴 선택", ["📸 문제 풀기", "📒 내 오답 노트"])
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.session_state['analysis_result'] = None
        st.rerun()

if menu == "📸 문제 풀기":
    with st.sidebar:
        st.markdown("---")
        
        # 🔥 [NEW] 교육과정 및 과목 선택 로직
        curriculum = st.radio("교육과정 선택", ["2015 개정 (현 고2~N수)", "2022 개정 (현 고1 이하)", "초등/중등 (공통)"])
        
        subject_options = []
        if "2015" in curriculum:
            subject_options = ["수학 (상/하)", "수학 I", "수학 II (다항함수 미적)", "미적분 (선택/심화)", "확률과 통계", "기하"]
        elif "2022" in curriculum:
            subject_options = ["공통수학 1/2", "대수 (구 수1)", "미적분 I (구 수2/다항미적)", "미적분 II (심화)", "확률과 통계", "기하"]
        else:
            subject_options = ["초등 수학", "중등 수학 (1~3학년)"]
            
        subject = st.selectbox("과목 선택", subject_options)

        # 말투 설정 (학년 대신 교육과정/과목 기반으로 추론)
        if "초등" in curriculum or "중등" in curriculum:
            tone = "친절하고 상세하게, 쉬운 용어로"
        else:
            tone = "명료하고 논리적으로, 핵심 위주로, 대치동 스타일"

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
            st.session_state['gemini_image'] = image_for_view
            
            link = "이미지_없음"
            with st.spinner("이미지 링크 생성 중..."):
                uploaded_link = upload_to_imgbb(img_bytes)
                if uploaded_link: link = uploaded_link

            with st.spinner(f"AI 선생님({MODEL_NAME})이 분석 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    
                    # 🔥 과목별 제약조건 생성
                    constraints = get_subject_constraints(curriculum, subject)
                    
                    prompt = f"""
                    당신은 대치동 1타 수학 강사입니다. 
                    - 설정: {curriculum}, {subject}
                    - 말투: {tone}
                    
                    [이미지 인식 지시 - 낙서 무시]
                    - 이미지의 빨간색 채점 표시나 연필 낙서는 철저히 무시하고, **검은색 인쇄 텍스트와 도형**만 인식하세요.
                    - 가려진 부분은 수학적 문맥으로 추론하여 복원하세요.

                    {constraints}
                    
                    [출력 형식 및 가독성 지시 - 엄수]
                    1. 첫 줄: [단원: 단원명]
                    
                    2. **핵심 개념:** <<<핵심>>> 태그와 <<<핵심끝>>> 태그 사이에 작성.
                    
                    3. **시각화:**
                       - 제목 쓰지 말고 오직 Code Block(```python ... ```)만 작성.
                       - 기하: `plt.axis('off')`, 함수: 축 표시.
                       - 원본=검은색, 보조선=빨간색 점선.
                    
                    4. **단계별 풀이 (가독성 핵심):**
                       - **줄글 금지:** 긴 문단을 쓰지 마세요. 
                       - **개조식 사용:** 모든 설명은 글머리 기호(-, •)를 사용하여 짧게 끊어 쓰세요.
                       - **수식 강조:** 모든 수식, 변수, 숫자는 반드시 LaTeX 형식($...$)을 사용하세요.
                       - **Step 구분:** **Step 1**, **Step 2** 처럼 볼드체로 단계를 명확히 나누세요.
                    
                    5. 쌍둥이 문제: 1문제 출제. 정답은 맨 뒤에 ===해설=== 구분선 넣고 작성.
                    """
                    
                    response = model.generate_content([prompt, st.session_state['gemini_image']])
                    st.session_state['analysis_result'] = response.text
                    
                    unit_name = "미분류"
                    if "[단원:" in response.text:
                        try: unit_name = response.text.split("[단원:")[1].split("]")[0].strip()
                        except: pass
                    
                    save_result_to_sheet(
                        st.session_state['user_name'], curriculum, unit_name, 
                        response.text, link
                    )
                    
                except Exception as e:
                    st.error(f"분석 오류: {e}")

    # --- [결과 화면] ---
    if st.session_state['analysis_result']:
        st.markdown("---")
        full_text = st.session_state['analysis_result']
        parts = full_text.split("===해설===")
        
        main_text, concept_text, graph_code = parse_response_smart(parts[0])
        
        with st.container(border=True):
            st.markdown("### 💡 선생님의 분석")
            
            # (1) 핵심 개념
            if concept_text:
                with st.expander("📚 필요한 핵심 개념 & 공식 (클릭)"):
                    st.markdown(concept_text)

            # (2) 그래프
            if graph_code:
                st.markdown("#### 📊 AI 자동 생성 그래프")
                with st.spinner("그래프 그리는 중..."):
                    exec_code_direct(graph_code)
            
            # (3) 메인 풀이
            st.markdown(main_text) 
        
        # 2. 정답 및 해설
        if len(parts) > 1:
            with st.expander("🔐 쌍둥이 문제 정답 및 해설 보기"):
                st.markdown(parts[1])
        
        # 3. 추가 생성
        if st.button("🔄 쌍둥이 문제 추가 생성"):
            with st.spinner("비슷한 문제 만드는 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    extra_prompt = f"""
                    위 문제와 비슷한 쌍둥이 문제를 1개 더. 정답은 ===해설=== 뒤에.
                    - 과정: {curriculum}, 과목: {subject} (제약조건 엄수)
                    - 그래프 코드는 오직 코드 블록만.
                    - 풀이는 개조식, LaTeX($...$) 사용.
                    """
                    res = model.generate_content([extra_prompt, st.session_state['gemini_image']])
                    p = res.text.split("===해설===")
                    ex_text, ex_con, ex_code = parse_response_smart(p[0])
                    with st.container(border=True):
                        st.markdown("#### ➕ 추가 문제")
                        if ex_code: exec_code_direct(ex_code)
                        st.markdown(ex_text)
                    if len(p) > 1:
                        with st.expander("🔐 정답 보기"):
                            st.markdown(p[1])
                except Exception as e:
                    st.error(f"오류: {e}")

# 오답노트
elif menu == "📒 내 오답 노트":
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
                            
                            if n_con: 
                                with st.expander("📚 핵심 개념"): st.markdown(n_con)
                            if n_code: 
                                if st.button(f"📊 그래프 보기 #{index}"): exec_code_direct(n_code)
                            
                            st.markdown(n_text) 
                            
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
                        if img_link: st.image(img_link, caption="원본 문제", use_container_width=True)
                        else: st.caption("이미지 없음")
        else: st.info("저장된 오답노트가 없습니다.")
    else: st.warning("데이터 로딩 실패")
