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

def save_result_to_sheet(student_name, category, sub_category, summary, link):
    client = get_sheet_client()
    if not client: return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        
        # 🔥 [수정됨] 서버 시간(UTC)에 9시간을 더해 한국 시간(KST)으로 변환
        kst = datetime.timezone(datetime.timedelta(hours=9))
        now = datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
        
        # 저장 컬럼: [날짜, 이름, 대분류(과정), 소분류(과목/학년), 내용, 링크, (공란), 복습횟수]
        sheet.append_row([now, student_name, category, sub_category, summary, link, "", 0])
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
# [NEW] 과정별/학년별 정밀 제약 조건 함수 (핵심!)
# ----------------------------------------------------------
def get_detailed_constraints(category, sub_selection):
    """
    category: 고등(2015), 고등(2022), 중등, 초등
    sub_selection: 과목명(고등) 또는 학년(중/초등)
    """
    base = f"현재 교육 단계: {category}, 세부 과정: {sub_selection}.\n"

    # [1] 초등 수학
    if "초등" in category:
        return base + """
        [⚠️ 초등 수학 풀이 가이드 - 절대 엄수]
        1. **변수 사용 금지:** $x, y$ 같은 미지수 대신 '$\square$(네모)', '어떤 수' 또는 '? '를 사용하세요.
        2. **방정식 금지:** 이항($+3$이 넘어가면 $-3$) 개념 대신, '거꾸로 계산하기'나 '직관적 덧셈/뺄셈'으로 설명하세요.
        3. **음수 금지:** 학생이 아직 음수(-) 개념을 모를 수 있으므로, 큰 수에서 작은 수를 빼는 형태로 식을 세우세요.
        4. **말투:** 아주 친절하게, 구체적인 예시(사과, 피자 등)를 들어 설명하세요.
        """

    # [2] 중등 수학
    elif "중등" in category:
        grade = sub_selection # 중1, 중2, 중3
        if "중1" in grade:
            return base + """
            [⚠️ 중1 수학 가이드]
            1. 문자와 식($x$)은 사용 가능하나, 연립방정식이나 부등식, 함수 용어($f(x)$)는 피하세요.
            2. 일차방정식 수준에서 해결하고, 기하 문제는 '작도와 합동' 관점에서 설명하세요.
            3. 음수와 정수 개념은 사용 가능합니다.
            """
        elif "중2" in grade:
            return base + """
            [⚠️ 중2 수학 가이드]
            1. 연립방정식, 일차부등식, 일차함수($y=ax+b$)를 사용하여 풀이하세요.
            2. 기하: 닮음, 피타고라스 정리(일부), 삼각형/사각형의 성질을 활용하세요.
            3. 제곱근($\sqrt{}$)이나 이차방정식은 사용하지 마세요.
            """
        elif "중3" in grade:
            return base + """
            [⚠️ 중3 수학 가이드]
            1. 제곱근($\sqrt{}$), 인수분해, 이차방정식, 이차함수, 삼각비($\sin, \cos$) 사용 가능합니다.
            2. **금지:** 고등 과정인 미분, 적분, 고차방정식(3차 이상), 나머지 정리 심화 개념은 사용하지 마세요.
            """

    # [3] 고등 수학 (2015 개정)
    elif "2015" in category:
        if "수학 II" in sub_selection:
            return base + """
            [⚠️ 고등 수학II(수2) 가이드]
            1. 다항함수의 미적분만 사용. (지수/로그/삼각함수 미분 금지)
            2. 로피탈 정리 금지. 정석 극한 풀이 사용.
            3. 음함수/매개변수 미분 금지.
            """
        elif "미적분" in sub_selection:
            return base + "[고등 미적분 가이드] 모든 미분법과 적분법을 자유롭게 사용하세요."
        elif "기하" in sub_selection:
            return base + "[고등 기하 가이드] 벡터, 공간도형 개념 사용 가능."
        else:
            return base + "[고등 수학 일반] 고1~고2 수준에 맞게 풀이하세요."

    # [4] 고등 수학 (2022 개정)
    elif "2022" in category:
        if "미적분 I" in sub_selection:
            return base + """
            [⚠️ 2022개정 미적분I (구 수2) 가이드]
            1. 다항함수의 미적분만 사용. 초월함수 미분 절대 금지.
            2. 교육과정 용어인 '미적분 I' 범위 내에서 해결하세요.
            """
        elif "대수" in sub_selection:
            return base + "[2022개정 대수 가이드] 지수/로그/삼각함수의 정의와 성질 활용 (미분 금지)."
        else:
            return base + "[2022개정 수학 일반] 해당 과목의 교육과정 범위를 준수하세요."
            
    return base

# ----------------------------------------------------------
# [5] 로그인 및 메인 로직
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
        
        # 🔥 1단계: 학교급/교육과정 선택
        course_category = st.radio(
            "과정 선택", 
            ["고등 (2015 개정)", "고등 (2022 개정)", "중등 수학", "초등 수학"]
        )
        
        # 🔥 2단계: 세부 과목 또는 학년 선택 (동적 변화)
        sub_selection = ""
        tone = "친절하게" # 기본 톤
        
        if "고등 (2015" in course_category:
            sub_selection = st.selectbox("과목 선택", ["수학 (상/하)", "수학 I", "수학 II (수2)", "미적분 (선택)", "확률과 통계", "기하"])
            tone = "대치동 1타 강사처럼 명료하고 핵심 위주로"
        elif "고등 (2022" in course_category:
            sub_selection = st.selectbox("과목 선택", ["공통수학 1/2", "대수", "미적분 I (구 수2)", "미적분 II (심화)", "확률과 통계", "기하"])
            tone = "대치동 1타 강사처럼 명료하고 핵심 위주로"
        elif "중등" in course_category:
            sub_selection = st.selectbox("학년 선택", ["중1", "중2", "중3"])
            tone = "친절하면서도 논리적으로, 개념 원리를 짚어주며"
        elif "초등" in course_category:
            sub_selection = st.selectbox("학년 선택", ["초3", "초4", "초5", "초6"])
            tone = "아주 친절하게, 쉬운 용어와 구어체(~해요) 사용"

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
                    
                    # 🔥 정밀 제약조건 생성
                    constraints = get_detailed_constraints(course_category, sub_selection)
                    
                    prompt = f"""
                    당신은 대치동 1타 수학 강사입니다. 
                    - 과정: {course_category}, 세부: {sub_selection}
                    - 말투: {tone}
                    
                    [이미지 인식 지시 - 낙서 무시]
                    - 빨간색 채점/연필 낙서 무시. 검은색 인쇄 텍스트/도형만 인식.
                    - 가려진 부분 문맥 추론 복원.

                    {constraints}
                    
                    [출력 형식 및 가독성 지시 - 엄수]
                    1. 첫 줄: [단원: 단원명]
                    
                    2. **핵심 개념:** <<<핵심>>> 태그와 <<<핵심끝>>> 태그 사이에 작성.
                    
                    3. **시각화:**
                       - 제목 쓰지 말고 오직 Code Block(```python ... ```)만 작성.
                       - 기하: `plt.axis('off')`, 함수: 축 표시.
                       - 원본=검은색, 보조선=빨간색 점선.
                    
                    4. **단계별 풀이 (가독성 핵심):**
                       - **줄글 금지.** 개조식(bullet point) 사용.
                       - **수식 강조:** LaTeX($...$) 형식 필수.
                       - **Step 구분:** **Step 1**, **Step 2** 볼드체 사용.
                       - 초등학생일 경우: $x$ 대신 $\square$ 사용, 친절한 구어체.
                    
                    5. 쌍둥이 문제: 1문제 출제. 정답은 맨 뒤에 ===해설=== 구분선 넣고 작성.
                    """
                    
                    response = model.generate_content([prompt, st.session_state['gemini_image']])
                    st.session_state['analysis_result'] = response.text
                    
                    unit_name = "미분류"
                    if "[단원:" in response.text:
                        try: unit_name = response.text.split("[단원:")[1].split("]")[0].strip()
                        except: pass
                    
                    # 저장 시에도 '과정(고등/중등)'과 '세부(과목/학년)'을 저장
                    save_result_to_sheet(
                        st.session_state['user_name'], course_category, sub_selection, 
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
            if concept_text:
                with st.expander("📚 필요한 핵심 개념 & 공식 (클릭)"):
                    st.markdown(concept_text)
            if graph_code:
                st.markdown("#### 📊 AI 자동 생성 그래프")
                with st.spinner("그래프 그리는 중..."):
                    exec_code_direct(graph_code)
            st.markdown(main_text) 
        
        if len(parts) > 1:
            with st.expander("🔐 쌍둥이 문제 정답 및 해설 보기"):
                st.markdown(parts[1])
        
        if st.button("🔄 쌍둥이 문제 추가 생성"):
            with st.spinner("비슷한 문제 만드는 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    extra_prompt = f"""
                    위 문제와 비슷한 쌍둥이 문제를 1개 더. 정답은 ===해설=== 뒤에.
                    - 과정: {course_category}, 세부: {sub_selection} (제약조건 엄수)
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
