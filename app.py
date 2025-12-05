import streamlit as st
from PIL import Image
import google.generativeai as genai
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime

# ----------------------------------------------------------
# [1] 기본 설정 및 API 연결
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫")

# (1) Gemini API 설정
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except:
    st.error("설정 오류: Secrets에 GOOGLE_API_KEY가 없습니다.")
    st.stop()

# (2) 구글 시트 연결 설정 (gspread)
def get_google_sheet_client():
    try:
        # Secrets에서 서비스 계정 정보 가져오기
        secrets = st.secrets["gcp_service_account"]
        
        # 👇 [핵심] 이 'scopes' 부분 두 줄이 없으면 403 오류가 납니다!
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # 권한 정보를 담아서 인증 요청
        credentials = Credentials.from_service_account_info(secrets, scopes=scopes)
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        st.error(f"구글 시트 연결 실패: {e}")
        return None

# ----------------------------------------------------------
# [2] 데이터 읽기/쓰기 함수 (핵심 기능!)
# ----------------------------------------------------------
# A. 학생 명단 불러오기 (Read)
def load_students_from_sheet():
    client = get_google_sheet_client()
    if not client: return None
    
    try:
        # ⚠️ 중요: 구글 시트 파일 이름을 정확히 적으세요! (예: MA학원_DB)
        sheet = client.open("MA학원_DB").worksheet("students")
        data = sheet.get_all_records() # 엑셀처럼 데이터를 가져옴
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"명단 불러오기 실패: {e}")
        return None

# B. 오답 결과 저장하기 (Write)
def save_result_to_sheet(student_name, grade, unit, analysis_summary):
    client = get_google_sheet_client()
    if not client: return
    
    try:
        sheet = client.open("MA학원_DB").worksheet("results")
        # 현재 시간
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 행 추가: [날짜, 이름, 학년, 단원, 내용(요약)]
        sheet.append_row([now, student_name, grade, unit, analysis_summary])
        st.toast("✅ 구글 시트에 오답 기록이 저장되었습니다!", icon="💾")
    except Exception as e:
        st.warning(f"데이터 저장 실패: {e}")

# ----------------------------------------------------------
# [3] 로그인 시스템
# ----------------------------------------------------------
if 'is_logged_in' not in st.session_state:
    st.session_state['is_logged_in'] = False
    st.session_state['user_name'] = None

def login_page():
    st.markdown("<h1 style='text-align: center;'>🔒 MA학원 로그인</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        user_id = st.text_input("아이디")
        user_pw = st.text_input("비밀번호", type="password")
        
        if st.button("로그인", use_container_width=True):
            with st.spinner("명단 확인 중..."):
                df = load_students_from_sheet()
            
            if df is not None:
                # id와 pw를 문자열로 변환해서 비교
                df['id'] = df['id'].astype(str)
                df['pw'] = df['pw'].astype(str)
                
                user_data = df[df['id'] == user_id]
                
                if not user_data.empty:
                    correct_pw = user_data.iloc[0]['pw']
                    user_name = user_data.iloc[0]['name']
                    
                    if user_pw == correct_pw:
                        st.session_state['is_logged_in'] = True
                        st.session_state['user_name'] = user_name
                        st.rerun()
                    else:
                        st.error("비밀번호가 틀렸습니다.")
                else:
                    st.error("등록되지 않은 아이디입니다.")
            else:
                st.error("학생 명단을 불러올 수 없습니다.")

if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

# ----------------------------------------------------------
# [4] 메인 앱 화면
# ----------------------------------------------------------
with st.sidebar:
    st.success(f"👋 {st.session_state['user_name']} 학생, 환영해!")
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.rerun()
        
    st.markdown("---")
    # 학년 선택
    student_grade = st.selectbox("학년 선택", ["초4", "초5", "초6", "중1", "중2", "중3", "고1(공통)", "고2(수1/2)", "고3(미적/확통)"])
    
    # 말투 설정
    if "초" in student_grade or "중1" in student_grade or "중2" in student_grade:
        tone = "친절하고 다정하게 격려하며"
    else:
        tone = "엄격하고 논리적으로 핵심만"

# 메인 UI
col1, col2 = st.columns([1, 4])
with col1:
    try: st.image("logo.png", use_container_width=True)
    except: st.write("🏫")
with col2:
    st.markdown("### 🏫 MA학원 AI 오답 도우미")

st.info("문제를 찍어서 올리면 AI 선생님이 분석하고 DB에 저장해줍니다.")

# 이미지 업로드
tab1, tab2 = st.tabs(["📸 카메라", "📂 갤러리"])
img_file = None
with tab1:
    cam = st.camera_input("촬영")
    if cam: img_file = cam
with tab2:
    up = st.file_uploader("파일 선택", type=['jpg', 'png'])
    if up: img_file = up

# 분석 실행
if img_file:
    st.image(img_file, caption="선택된 문제")
    
    if st.button("🔍 분석 및 저장 시작", type="primary"):
        with st.spinner("분석 중... 잠시만 기다려주세요."):
            try:
                # 1. AI 분석 (Gemini 2.5 Flash 사용)
                model = genai.GenerativeModel('gemini-2.5-flash')
               # ---------------------------------------------------------
                # [수정된 프롬프트] 대치동 1타 강사 버전
                # ---------------------------------------------------------
                prompt = f"""
                [Role Definition]
                당신은 대한민국 '대치동에서 20년 이상 수능과 내신을 지도한 수학 전문 1타 강사'입니다.
                단순한 정답 판별기가 아니라, 학생의 사고력을 키워주는 멘토입니다.
                현재 학생의 학년/과목: **{student_grade}**
                
                [Task Description]
                제공된 수학 문제 이미지를 '철저하게 분석'하여 풀이를 작성하세요.
                
                [Output Format & Rules]
                1. **단원 명시**: 맨 첫 줄에 반드시 `[단원: 대단원 > 중단원]` 형식으로 정확히 적으세요.
                2. **출제 의도 파악**: 이 문제가 요구하는 핵심 개념이 무엇인지 한 문장으로 요약하세요.
                3. **단계별 풀이 (Step-by-Step)**: 
                   - 암산하듯 건너뛰지 말고, 논리적 흐름을 1단계, 2단계로 나누어 상세히 설명하세요.
                   - 수식은 LaTeX 포맷을 사용하여 깔끔하게 표현하세요.
                4. **오답 포인트(Tip)**: 
                   - "이 부분에서 학생들이 자주 실수한다"는 20년 경력의 노하우(함정)를 짚어주세요.
                5. **말투 적용**: 
                   - "{tone}" 
                   - (위 말투 지침을 어기지 말고 철저히 지키세요.)
                6. **쌍둥이 문제**: 
                   - 마지막에 이 문제와 풀이 논리는 같지만 숫자나 형태가 다른 '변형 문제' 1개를 추가하세요.
                   - 정답도 함께 적어주세요.
                """
                """
                response = model.generate_content([prompt, Image.open(img_file)])
                result_text = response.text
                
                # 2. 결과 출력
                st.markdown("### 📝 분석 결과")
                st.write(result_text)
                
                # 3. 단원명 추출 (저장용)
                unit_name = "미분류"
                if "[단원:" in result_text:
                    try:
                        unit_name = result_text.split("[단원:")[1].split("]")[0].strip()
                    except: pass
                
                # 4. 구글 시트에 자동 저장
                save_result_to_sheet(
                    st.session_state['user_name'], 
                    student_grade, 
                    unit_name, 
                    result_text[:100] + "..." # 내용은 너무 기니까 앞부분만 요약 저장
                )
                
            except Exception as e:
                st.error(f"오류 발생: {e}")




