import streamlit as st
from PIL import Image
import google.generativeai as genai
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import datetime
import io

# ----------------------------------------------------------
# [1] 설정 (ID 유지)
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫")

SHEET_ID = "1zJ2rs68pSE9Ntesg1kfqlI7G22ovfxX8Fb7v7HgxzuQ"
FOLDER_ID = "1zl6EoXAitDFUWVYoLBtorSJw-JrOm_fG"

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except:
    st.error("Secrets에 GOOGLE_API_KEY가 없습니다.")
    st.stop()

# ----------------------------------------------------------
# [2] 구글 연결 (시트 & 드라이브)
# ----------------------------------------------------------
def get_credentials():
    try:
        secrets = st.secrets["gcp_service_account"]
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(secrets, scopes=scopes)
        return creds
    except Exception as e:
        st.error(f"인증 실패: {e}")
        return None

# ----------------------------------------------------------
# [3] 드라이브 업로드 (안전장치 포함)
# ----------------------------------------------------------
def upload_image_to_drive(image_file, student_name):
    creds = get_credentials()
    if not creds: return None

    try:
        service = build('drive', 'v3', credentials=creds)
        filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{student_name}.jpg"
        
        file_metadata = {
            'name': filename,
            'parents': [FOLDER_ID] 
        }
        media = MediaIoBaseUpload(image_file, mimetype='image/jpeg')
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        return file.get('webViewLink')
        
    except Exception as e:
        print(f"업로드 실패 (분석은 진행): {e}") 
        return "업로드_실패(용량부족)"

# ----------------------------------------------------------
# [4] 시트 데이터 저장
# ----------------------------------------------------------
def save_result_to_sheet(student_name, grade, unit, analysis_summary, image_link):
    creds = get_credentials()
    if not creds: return
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([now, student_name, grade, unit, analysis_summary, image_link])
        st.toast("✅ 학습 데이터 저장 완료!", icon="💾")
    except Exception as e:
        st.error(f"시트 저장 실패: {e}")

def load_students_from_sheet():
    creds = get_credentials()
    if not creds: return None
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).worksheet("students")
        return pd.DataFrame(sheet.get_all_records())
    except Exception as e:
        st.error(f"명단 오류: {e}")
        return None

# ----------------------------------------------------------
# [5] 메인 로직 (로그인 및 UI)
# ----------------------------------------------------------
# 세션 상태 초기화 (새로고침 해도 데이터 유지용)
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
            with st.spinner("확인 중..."):
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
            else: st.error("명단 로딩 실패")

if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

# --- 사이드바 ---
with st.sidebar:
    st.success(f"👋 {st.session_state['user_name']} 학생")
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.session_state['analysis_result'] = None # 로그아웃 시 분석결과 초기화
        st.rerun()
    st.markdown("---")
    student_grade = st.selectbox("학년", ["초4", "초5", "초6", "중1", "중2", "중3", "고1", "고2", "고3"])
    
    # 학년별 말투 설정
    if any(x in student_grade for x in ["초", "중1", "중2"]):
        tone = "친절하고 상세하게, 하지만 핵심은 정확하게 짚어주며"
    else:
        tone = "대치동 1타 강사처럼 엄격하고 논리정연하게, 팩트 위주로"

st.markdown("### 🏫 MA학원 AI 오답 도우미")

tab1, tab2 = st.tabs(["📸 카메라", "📂 갤러리"])
img_file = None
with tab1:
    cam = st.camera_input("촬영")
    if cam: img_file = cam
with tab2:
    up = st.file_uploader("파일 선택", type=['jpg', 'png'])
    if up: img_file = up

# ----------------------------------------------------------
# [6] 분석 실행 로직 (강화된 페르소나 + 정답 가리기)
# ----------------------------------------------------------
if img_file:
    # 이미지를 바이트로 변환하여 세션 및 업로드용으로 준비
    img_bytes = img_file.getvalue()
    image_for_view = Image.open(io.BytesIO(img_bytes))
    
    st.image(image_for_view, caption="선택된 문제")

    # 분석 버튼
    if st.button("🔍 1타 강사 분석 시작", type="primary"):
        # 1. 이미지 세션에 저장 (나중에 추가 생성할 때 쓰려고)
        st.session_state['gemini_image'] = Image.open(io.BytesIO(img_bytes))
        image_for_upload = io.BytesIO(img_bytes)

        # 2. 드라이브 업로드 (실패해도 진행)
        with st.spinner("사진 저장 중..."):
            link = upload_image_to_drive(image_for_upload, st.session_state['user_name'])

        # 3. AI 분석
        with st.spinner("대치동 20년 경력 선생님이 분석 중입니다..."):
            try:
                model = genai.GenerativeModel('gemini-1.5-flash')
                
                # 🔥 강화된 프롬프트
                prompt = f"""
                당신은 '대치동 수학 학원에서 20년 이상 학생들을 가르친 최고의 베테랑 강사'입니다.
                학생 학년: {student_grade}
                말투: {tone}
                
                [반드시 지켜야 할 지시사항]
                1. 첫 줄에 [단원: 단원명]을 명시하세요.
                2. 문제 풀이는 매우 꼼꼼하고 철저하게 작성하세요. 학생이 자주 틀리는 실수 포인트가 있다면 따끔하게 지적해주세요.
                3. 마지막에 숫자와 조건만 바꾼 '쌍둥이 문제'를 1개 출제하세요.
                4. **중요:** 쌍둥이 문제의 정답과 풀이는 맨 마지막에 **===해설===** 이라는 구분선을 넣고 그 뒤에 작성하세요. (학생이 바로 답을 못 보게 하기 위함입니다)
                """
                
                response = model.generate_content([prompt, st.session_state['gemini_image']])
                st.session_state['analysis_result'] = response.text # 결과 기억하기
                
                # 시트 저장
                unit_name = "미분류"
                if "[단원:" in response.text:
                    try: unit_name = response.text.split("[단원:")[1].split("]")[0].strip()
                    except: pass
                
                save_result_to_sheet(
                    st.session_state['user_name'], 
                    student_grade, 
                    unit_name, 
                    response.text[:300] + "...", 
                    link
                )
                
            except Exception as e:
                st.error(f"분석 오류: {e}")

# ----------------------------------------------------------
# [7] 결과 보여주기 (정답 가리기 기능 적용)
# ----------------------------------------------------------
if st.session_state['analysis_result']:
    st.markdown("---")
    st.markdown("### 📝 선생님의 분석 결과")
    
    # 결과를 '===해설===' 기준으로 자름
    full_text = st.session_state['analysis_result']
    parts = full_text.split("===해설===")
    
    # 1부: 분석 내용 + 쌍둥이 문제 (정답 없음)
    st.write(parts[0])
    
    # 2부: 정답 (버튼 눌러야 보임)
    if len(parts) > 1:
        with st.expander("🔐 쌍둥이 문제 정답 및 해설 보기 (클릭)"):
            st.info("먼저 풀어보고 확인하세요!")
            st.write(parts[1])
            
    st.markdown("---")
    
    # [8] 쌍둥이 문제 추가 생성 버튼
    if st.button("🔄 쌍둥이 문제 더 만들기 (추가 생성)"):
        with st.spinner("비슷한 문제를 하나 더 만드는 중..."):
            try:
                model = genai.GenerativeModel('gemini-1.5-flash')
                extra_prompt = f"""
                위의 문제와 난이도가 비슷한 새로운 쌍둥이 문제를 1개 더 만들어주세요.
                학생 학년: {student_grade}
                말투: {tone}
                **중요:** 이번에도 정답과 해설은 맨 마지막에 **===해설===** 구분선을 넣고 그 뒤에 적어주세요.
                """
                # 이전에 저장해둔 이미지를 다시 활용
                response_extra = model.generate_content([extra_prompt, st.session_state['gemini_image']])
                
                # 추가 문제 출력 로직
                extra_parts = response_extra.text.split("===해설===")
                st.markdown("#### ➕ 추가 쌍둥이 문제")
                st.write(extra_parts[0])
                
                if len(extra_parts) > 1:
                    with st.expander("🔐 추가 문제 정답 보기"):
                        st.write(extra_parts[1])
                        
            except Exception as e:
                st.error(f"추가 생성 실패: {e}")
