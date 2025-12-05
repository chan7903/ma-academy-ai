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

# (2) 구글 시트 연결 설정
def get_google_sheet_client():
    try:
        secrets = st.secrets["gcp_service_account"]
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = Credentials.from_service_account_info(secrets, scopes=scopes)
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        st.error(f"구글 시트 연결 실패: {e}")
        return None

# ----------------------------------------------------------
# [2] 데이터 읽기/쓰기 함수
# ----------------------------------------------------------
def load_students_from_sheet():
    client = get_google_sheet_client()
    if not client: return None
    try:
        sheet = client.open("MA학원_DB").worksheet("students")
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"명단 불러오기 실패: {e}")
        return None

def save_result_to_sheet(student_name, grade, unit, analysis_summary):
    client = get_google_sheet_client()
    if not client: return
    try:
        sheet = client.open("MA학원_DB").worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([now, student_name, grade, unit, analysis_summary])
        st.toast("✅ 구글 시트에 저장 완료!", icon="💾")
    except Exception as e:
        st.warning(f"저장 실패: {e}")

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
                df['id'] = df['id'].astype(str)
                df['pw'] = df['pw'].astype(str)
                user_data = df[df['id'] == user_id]
                if not user_data.empty:
                    if user_pw == user_data.iloc[0]['pw']:
                        st.session_state['is_logged_in'] = True
                        st.session_state['user_name'] = user_data.iloc[0]['name']
                        st.rerun()
                    else: st.error("비밀번호가 틀렸습니다.")
                else: st.error("등록되지 않은 아이디입니다.")
            else: st.error("등록되지 않은 아이디입니다.")

if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

# ----------------------------------------------------------
# [4] 메인 화면 UI
# ----------------------------------------------------------
with st.sidebar:
    st.success(f"👋 {st.session_state['user_name']} 학생, 환영해!")
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.rerun()
    st.markdown("---")
    subject_options = [
        "초4", "초5", "초6",
        "중1", "중2", "중3",
        "공통수학1", "공통수학2", "대수", "미적분1",
        "수1", "수2", "미적분", "확통"
    ]
    student_grade = st.selectbox("학년 및 과목 선택", subject_options)
    
    if student_grade in ["초4", "초5", "초6", "중1", "중2"]:
        st.info("💡 모드: 친절한 격려 모드")
        tone = "친절하고 다정하게, 칭찬과 격려를 많이 해주세요."
    else:
        st.info("💡 모드: 엄격한 입시 모드")
        tone = "엄격하고 건조하게. 팩트와 논리 위주로 설명하세요."

col1, col2 = st.columns([1, 4])
with col1:
    try: st.image("logo.png", use_container_width=True)
    except: st.write("🏫")
with col2:
    st.markdown("### MA학원 AI 오답 도우미")
st.markdown("---")

# ----------------------------------------------------------
# [5] 문제 입력
# ----------------------------------------------------------
st.markdown("##### 1. 문제 업로드")
tab1, tab2 = st.tabs(["📸 카메라 촬영", "📂 갤러리 업로드"])

img_file = None
with tab1: camera_img = st.camera_input("문제 촬영")
with tab2: uploaded_img = st.file_uploader("이미지 파일 선택", type=['jpg', 'png', 'jpeg'])

if uploaded_img:
    img_file = uploaded_img
    st.success("✅ 갤러리 이미지가 선택되었습니다.")
elif camera_img:
    img_file = camera_img
    st.success("✅ 촬영된 이미지가 선택되었습니다.")

# ----------------------------------------------------------
# [6] AI 분석 실행 (Gemini 2.5 Flash)
# ----------------------------------------------------------
if img_file:
    image = Image.open(img_file)
    st.image(image, caption="선택된 문제", use_container_width=True)

    if st.button("🔍 AI 분석 시작", type="primary"):
        with st.spinner("대치동 1타 강사 AI가 분석 중입니다..."):
            try:
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                # 👇 [프롬프트 수정] 정답을 숨기기 위해 '구분자' 명령 추가
                prompt = f"""
                [Role Definition]
                당신은 대한민국 '대치동에서 20년 이상 수능과 내신을 지도한 수학 전문 1타 강사'입니다.
                현재 학생의 학년/과목: **{student_grade}**
                
                [Output Format & Rules]
                1. **단원 명시**: 첫 줄에 `[단원: 대단원 > 중단원]` 적기.
                2. **출제 의도**: 핵심 개념 1줄 요약.
                3. **단계별 풀이**: 논리적 흐름에 따라 상세히 설명.
                4. **오답 포인트**: 학생들이 자주 틀리는 함정 언급.
                5. **말투**: "{tone}"
                
                6. **쌍둥이 문제 (중요)**:
                   - 맨 마지막에 변형 문제 1개를 내주세요.
                   - **[중요]** 문제 지문까지만 적고, 그 바로 밑에 반드시 `[[정답_및_해설_시작]]` 이라고 구분자를 적어주세요.
                   - 구분자 아래쪽에 정답과 풀이 과정을 적어주세요.
                """
                
                response = model.generate_content([prompt, image])
                
                # 결과 저장
                st.session_state['analysis_result'] = response.text
                st.session_state['last_image'] = image
                
                # 구글 시트 저장 (요약본)
                unit_name = "미분류"
                if "[단원:" in response.text:
                    try: unit_name = response.text.split("[단원:")[1].split("]")[0].strip()
                    except: pass
                save_result_to_sheet(st.session_state['user_name'], student_grade, unit_name, response.text[:200] + "...")
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")

# ----------------------------------------------------------
# [7] 결과 출력 (숨김 기능 적용)
# ----------------------------------------------------------
if 'analysis_result' in st.session_state:
    st.markdown("### 📝 분석 결과")
    
    # 👇 [화면 출력 로직] 구분자를 기준으로 내용을 자릅니다!
    full_text = st.session_state['analysis_result']
    separator = "[[정답_및_해설_시작]]"
    
    if separator in full_text:
        parts = full_text.split(separator)
        st.write(parts[0]) # 1. 문제 분석 내용 + 쌍둥이 문제 지문 (보여줌)
        
        with st.expander("🔐 쌍둥이 문제 정답 및 해설 보기 (클릭)"):
            st.write(parts[1]) # 2. 정답 및 해설 (숨김)
    else:
        st.write(full_text) # 구분자가 없으면 그냥 다 보여줌
    
    # 추가 생성 버튼
    if st.button("🔄 쌍둥이 문제 더 만들기"):
         with st.spinner("생성 중..."):
            try:
                model = genai.GenerativeModel('gemini-2.5-flash')
                extra_prompt = f"""
                위와 비슷한 쌍둥이 문제 2개를 더 만들어줘. 학년: {student_grade}
                단, 문제 지문 다음에 `[[정답_및_해설_시작]]` 구분자를 넣고, 그 밑에 정답과 해설을 적어줘.
                """
                
                if 'last_image' in st.session_state:
                    response_extra = model.generate_content([extra_prompt, st.session_state['last_image']])
                else:
                    response_extra = model.generate_content(extra_prompt)
                
                st.markdown("#### ➕ 추가 문제")
                
                # 추가 문제도 똑같이 숨김 처리
                extra_text = response_extra.text
                if separator in extra_text:
                    ex_parts = extra_text.split(separator)
                    st.write(ex_parts[0])
                    with st.expander("🔐 추가 문제 정답 보기"):
                        st.write(ex_parts[1])
                else:
                    st.write(extra_text)
                    
            except Exception as e:
                st.error(f"추가 생성 오류: {e}")
