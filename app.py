import streamlit as st
from PIL import Image
import google.generativeai as genai
import pandas as pd

# ----------------------------------------------------------
# [1] 페이지 및 API 설정
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫")

# Streamlit Cloud 배포용 비밀키 불러오기
# (주의: Streamlit Cloud 설정 페이지의 Secrets에 GOOGLE_API_KEY를 등록해야 작동합니다)
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except:
    st.error("API 키 오류: Streamlit Cloud 설정(Secrets)에 GOOGLE_API_KEY를 입력해주세요.")
    st.stop()

# ----------------------------------------------------------
# [2] 로그인 시스템 (학생 관리)
# ----------------------------------------------------------
# 학생 아이디와 비밀번호를 여기에 적어주세요
STUDENTS = {
    "student1": "1234",   # 예시 학생 1
    "student2": "1111",   # 예시 학생 2
    "admin": "1234"       # 원장님 테스트용
}

if 'is_logged_in' not in st.session_state:
    st.session_state['is_logged_in'] = False
    st.session_state['user_id'] = None

def login_page():
    st.markdown("<h1 style='text-align: center;'>🔒 MA학원 로그인</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>학생 아이디와 비밀번호를 입력하세요.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        user_id = st.text_input("아이디")
        user_pw = st.text_input("비밀번호", type="password")
        
        if st.button("로그인", use_container_width=True):
            if user_id in STUDENTS and STUDENTS[user_id] == user_pw:
                st.session_state['is_logged_in'] = True
                st.session_state['user_id'] = user_id
                st.rerun() # 화면 새로고침
            else:
                st.error("아이디 또는 비밀번호가 틀렸습니다.")

# 로그인이 안 되어 있으면 로그인 화면만 보여주고 멈춤
if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

# ----------------------------------------------------------
# [3] 사이드바 설정 (로그인 후 보임)
# ----------------------------------------------------------
with st.sidebar:
    st.success(f"👋 환영합니다, {st.session_state['user_id']}님!")
    
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.rerun()
        
    st.markdown("---")
    st.header("📚 학생 설정")
    
    # 2022 개정 교육과정 반영 과목 리스트
    subject_options = [
        "초4", "초5", "초6",
        "중1", "중2", "중3",
        "공통수학1", "공통수학2", "대수", "미적분1",
        "수1", "수2", "미적분", "확통"
    ]
    student_grade = st.selectbox("학년 및 과목 선택", subject_options)
    
    # 학년별 말투 설정 로직
    young_grades = ["초4", "초5", "초6", "중1", "중2"]
    
    if student_grade in young_grades:
        st.info("💡 모드: 친절한 격려 모드")
        tone_instruction = """
        - 대상: 초등~중2 학생.
        - 말투: 친절하고 다정하게, 칭찬과 격려를 많이 해주세요. (예: "정말 아까웠어!", "다음에 꼭 맞출 수 있어!")
        - 설명: 이해하기 쉽게 쉬운 비유를 사용하세요.
        - 이모지: 적절히 사용하여 분위기를 밝게 하세요.
        """
    else:
        st.info("💡 모드: 엄격한 입시 모드")
        tone_instruction = """
        - 대상: 중3 및 고등학생 (입시 준비).
        - 말투: 엄격하고 건조하게. 감정적인 위로보다는 팩트와 논리 위주로 설명하세요. (예: "이 개념 부재가 오답 원인임.", "풀이 과정을 다시 점검할 것.")
        - 설명: 간결하고 핵심만 짚으세요. 유치한 격려는 하지 마세요.
        - 이모지: 사용하지 마세요.
        """

# ----------------------------------------------------------
# [4] 메인 화면 디자인 (로고 + 타이틀)
# ----------------------------------------------------------
col1, col2 = st.columns([1, 4])

with col1:
    # ⚠️ GitHub에 올린 로고 파일명(대소문자)과 정확히 일치해야 합니다!
    try:
        st.image("logo.png", use_container_width=True)
    except:
        st.warning("로고 파일 없음") # 로고 파일이 없어도 앱이 꺼지지 않게 처리

with col2:
    st.markdown("""
        <div style='text-align: left; padding-top: 10px;'>
            <h1 style='margin-bottom: 0;'>MA학원</h1>
            <h3 style='margin-top: 0; color: gray;'>AI 오답 도우미</h3>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<hr>", unsafe_allow_html=True)

# ----------------------------------------------------------
# [5] 문제 입력 (카메라 & 갤러리)
# ----------------------------------------------------------
st.markdown("##### 1. 문제 업로드")
tab1, tab2 = st.tabs(["📸 카메라 촬영", "📂 갤러리 업로드"])

img_file = None

with tab1:
    camera_img = st.camera_input("문제 촬영") 
    if camera_img:
        img_file = camera_img

with tab2:
    uploaded_img = st.file_uploader("이미지 파일 선택", type=['jpg', 'png', 'jpeg'])
    if uploaded_img:
        img_file = uploaded_img

# ----------------------------------------------------------
# [6] AI 분석 실행
# ----------------------------------------------------------
if img_file:
    image = Image.open(img_file)
    st.image(image, caption="선택된 문제", use_container_width=True)

    if st.button("🔍 AI 분석 시작", type="primary"):
        with st.spinner("MA학원 AI 선생님이 분석 중입니다..."):
            try:
                model = genai.GenerativeModel('gemini-1.5-flash')
                
                prompt = f"""
                당신은 20년 경력의 수학 전문 강사입니다. 
                현재 학생의 학년/과목은 **{student_grade}**입니다.
                
                [지시사항]
                1. 이미지 속 문제를 텍스트(LaTeX 포함)로 정확히 변환하세요.
                2. 이 문제의 **'단원명'**을 반드시 첫 줄에 명시하세요. (형식: [단원: 단원명])
                3. 학생의 눈높이에 맞춰 상세한 풀이를 제공하세요.
                4. **말투 지침**: {tone_instruction}
                5. 풀이 마지막에 이 문제와 숫자만 바꾼 **'쌍둥이 문제'** 1개를 만들어주세요.
                """
                
                response = model.generate_content([prompt, image])
                
                # 결과 저장
                st.session_state['analysis_result'] = response.text
                st.session_state['last_image'] = image # 추가 생성을 위해 이미지 기억
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")

# ----------------------------------------------------------
# [7] 결과 표시 및 추가 기능
# ----------------------------------------------------------
if 'analysis_result' in st.session_state:
    st.markdown("### 📝 분석 결과")
    st.write(st.session_state['analysis_result'])
    
    st.markdown("---")
    
    # 쌍둥이 문제 추가 버튼
    if st.button("🔄 쌍둥이 문제 더 만들기"):
         with st.spinner("비슷한 문제를 추가로 생성 중..."):
            try:
                model = genai.GenerativeModel('gemini-1.5-flash')
                extra_prompt = f"""
                방금 푼 문제와 동일한 유형의 **쌍둥이 문제 2개**를 더 만들어줘.
                학년: {student_grade}
                말투: {tone_instruction}
                정답과 해설은 맨 아래에 따로 적어줘.
                """
                
                # 이미지가 있으면 이미지도 같이 보냄 (정확도 향상)
                if 'last_image' in st.session_state:
                    response_extra = model.generate_content([extra_prompt, st.session_state['last_image']])
                else:
                    response_extra = model.generate_content(extra_prompt)
                    
                st.markdown("#### ➕ 추가 쌍둥이 문제")
                st.write(response_extra.text)
            except Exception as e:
                st.error(f"추가 생성 중 오류: {e}")

# ----------------------------------------------------------
# [8] 오답노트 & 통계 (예시)
# ----------------------------------------------------------
st.markdown("---")
st.header("📊 내 오답노트 관리")

# (임시 가짜 데이터)
data = {
    '단원': ['이차방정식', '이차방정식', '삼각함수', '수열', '다항식', '이차방정식'],
    '날짜': ['5/1', '5/2', '5/3', '5/5', '5/6', '5/7'],
    '결과': ['오답', '오답', '정답', '오답', '정답', '오답']
}
df = pd.DataFrame(data)

stat_tab1, stat_tab2 = st.tabs(["📉 취약 단원 분석", "📜 전체 리스트"])

with stat_tab1:
    wrong_df = df[df['결과'] == '오답']
    if not wrong_df.empty:
        counts = wrong_df['단원'].value_counts()
        st.bar_chart(counts)
        st.caption("그래프가 높은 단원이 취약한 단원입니다.")
    else:
        st.write("오답 데이터가 없습니다.")

with stat_tab2:
    st.dataframe(df, use_container_width=True)
