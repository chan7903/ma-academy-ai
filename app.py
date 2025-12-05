import streamlit as st
from PIL import Image
import google.generativeai as genai
import pandas as pd

# ----------------------------------------------------------
# [1] 페이지 및 API 설정
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫")

# Streamlit Cloud 배포용 비밀키 불러오기
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except:
    st.error("API 키 오류: Streamlit Cloud 설정(Secrets)에 GOOGLE_API_KEY를 입력해주세요.")
    st.stop()

# ----------------------------------------------------------
# [2] 로그인 시스템 (CSV 파일 연동)
# ----------------------------------------------------------
if 'is_logged_in' not in st.session_state:
    st.session_state['is_logged_in'] = False
    st.session_state['user_id'] = None
    st.session_state['user_name'] = None

def load_students():
    try:
        df = pd.read_csv("students.csv", dtype=str)
        return df
    except:
        return None

def login_page():
    st.markdown("<h1 style='text-align: center;'>🔒 MA학원 로그인</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        user_id = st.text_input("아이디")
        user_pw = st.text_input("비밀번호", type="password")
        
        if st.button("로그인", use_container_width=True):
            df = load_students()
            
            # 1. 파일이 있으면 파일로 검사
            if df is not None:
                user_data = df[df['id'] == user_id]
                if not user_data.empty:
                    correct_pw = user_data.iloc[0]['pw']
                    user_name = user_data.iloc[0]['name']
                    if user_pw == correct_pw:
                        st.session_state['is_logged_in'] = True
                        st.session_state['user_id'] = user_id
                        st.session_state['user_name'] = user_name
                        st.rerun()
                    else:
                        st.error("비밀번호가 틀렸습니다.")
                else:
                    st.error("등록되지 않은 아이디입니다.")
            
            # 2. 파일이 없으면 비상용 관리자 계정 (테스트용)
            elif user_id == "admin" and user_pw == "1234":
                st.session_state['is_logged_in'] = True
                st.session_state['user_id'] = "admin"
                st.session_state['user_name'] = "원장님(비상용)"
                st.rerun()
            else:
                st.error("학생 명단 파일이 없고 관리자 계정도 아닙니다.")

if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

# ----------------------------------------------------------
# [3] 사이드바 설정
# ----------------------------------------------------------
with st.sidebar:
    st.success(f"👋 환영합니다, {st.session_state['user_name']}님!")
    
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.rerun()
        
    st.markdown("---")
    st.header("📚 학생 설정")
    
    subject_options = [
        "초4", "초5", "초6",
        "중1", "중2", "중3",
        "공통수학1", "공통수학2", "대수", "미적분1",
        "수1", "수2", "미적분", "확통"
    ]
    student_grade = st.selectbox("학년 및 과목 선택", subject_options)
    
    young_grades = ["초4", "초5", "초6", "중1", "중2"]
    
    if student_grade in young_grades:
        st.info("💡 모드: 친절한 격려 모드")
        tone_instruction = "친절하고 다정하게, 칭찬과 격려를 많이 해주세요."
    else:
        st.info("💡 모드: 엄격한 입시 모드")
        tone_instruction = "엄격하고 건조하게. 팩트와 논리 위주로 설명하세요."

# ----------------------------------------------------------
# [4] 메인 화면
# ----------------------------------------------------------
col1, col2 = st.columns([1, 4])
with col1:
    try:
        st.image("logo.png", use_container_width=True)
    except:
        st.write("🏫")
with col2:
    st.markdown("### MA학원 AI 오답 도우미")

st.markdown("---")

# ----------------------------------------------------------
# [5] 문제 입력 (갤러리 우선)
# ----------------------------------------------------------
st.markdown("##### 1. 문제 업로드")
tab1, tab2 = st.tabs(["📸 카메라 촬영", "📂 갤러리 업로드"])

img_file = None

with tab1:
    camera_img = st.camera_input("문제 촬영")

with tab2:
    uploaded_img = st.file_uploader("이미지 파일 선택", type=['jpg', 'png', 'jpeg'])

# 갤러리 이미지가 있으면 그걸 우선으로 씁니다!
if uploaded_img:
    img_file = uploaded_img
    st.success("✅ 갤러리 이미지가 선택되었습니다.")
elif camera_img:
    img_file = camera_img
    st.success("✅ 촬영된 이미지가 선택되었습니다.")

# ----------------------------------------------------------
# [6] AI 분석 실행 (Gemini 2.5 Flash 적용)
# ----------------------------------------------------------
if img_file:
    image = Image.open(img_file)
    st.image(image, caption="선택된 문제", use_container_width=True)

    if st.button("🔍 AI 분석 시작", type="primary"):
        with st.spinner("MA학원 AI(2.5 Flash)가 분석 중입니다..."):
            try:
                # 👇 [중요] 원장님이 원하시는 2.5 Flash 모델로 변경했습니다!
                model_name = 'gemini-2.5-flash' 
                model = genai.GenerativeModel(model_name)
                
                prompt = f"""
                당신은 수학 강사입니다. 학생: {student_grade}
                [지시사항]
                1. 문제의 '단원명'을 첫 줄에 [단원: OOO] 형식으로 적으세요.
                2. 상세한 풀이를 작성하세요.
                3. 말투: {tone_instruction}
                4. 마지막에 쌍둥이 문제 1개를 만드세요.
                """
                
                response = model.generate_content([prompt, image])
                
                st.session_state['analysis_result'] = response.text
                st.session_state['last_image'] = image
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
                st.warning("혹시 API 키가 2.5 버전을 지원하지 않거나, 모델명이 정확한지 확인해주세요.")

# ----------------------------------------------------------
# [7] 결과 표시
# ----------------------------------------------------------
if 'analysis_result' in st.session_state:
    st.markdown("### 📝 분석 결과")
    st.write(st.session_state['analysis_result'])
    
    if st.button("🔄 쌍둥이 문제 더 만들기"):
         with st.spinner("생성 중..."):
            try:
                # 👇 추가 생성할 때도 2.5 버전을 사용합니다.
                model = genai.GenerativeModel('gemini-2.5-flash')
                extra_prompt = f"위와 비슷한 쌍둥이 문제 2개 더 생성. 학년: {student_grade}"
                
                if 'last_image' in st.session_state:
                    response_extra = model.generate_content([extra_prompt, st.session_state['last_image']])
                else:
                    response_extra = model.generate_content(extra_prompt)
                    
                st.markdown("#### ➕ 추가 문제")
                st.write(response_extra.text)
            except Exception as e:
                st.error(f"추가 생성 오류: {e}")
