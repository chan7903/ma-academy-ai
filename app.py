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
# [1] 기본 설정
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫")

# 비밀번호 및 API 키 로드
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except:
    st.error("설정 오류: Secrets에 GOOGLE_API_KEY가 없습니다.")
    st.stop()

# 인증 정보 가져오기 (공통 함수)
def get_credentials():
    try:
        secrets = st.secrets["gcp_service_account"]
        # 드라이브와 시트 모두 접근 가능한 권한 설정
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = Credentials.from_service_account_info(secrets, scopes=scopes)
        return credentials
    except Exception as e:
        st.error(f"인증 정보 로드 실패: {e}")
        return None

# 구글 시트 클라이언트
def get_google_sheet_client():
    try:
        # Secrets에서 서비스 계정 정보 가져오기
        secrets = st.secrets["gcp_service_account"]
        
        # 👇 [핵심] 권한 범위를 '시트'와 '드라이브' 모두로 넓혀야 오류가 안 납니다!
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

# 구글 드라이브 서비스
def get_drive_service():
    creds = get_credentials()
    if creds:
        return build('drive', 'v3', credentials=creds)
    return None

# ----------------------------------------------------------
# [2] 데이터 함수 (이미지 업로드 기능 추가됨!)
# ----------------------------------------------------------

# (A) 이미지를 구글 드라이브에 업로드하고 링크를 가져오는 함수
def upload_image_to_drive(image_obj, file_name):
    try:
        service = get_drive_service()
        
        # 1. 이미지를 바이트로 변환
        img_byte_arr = io.BytesIO()
        image_obj.save(img_byte_arr, format=image_obj.format)
        img_byte_arr.seek(0)
        
        # 2. 파일 메타데이터 (이름 설정)
        file_metadata = {'name': file_name}
        
        # 3. 업로드 실행
        media = MediaIoBaseUpload(img_byte_arr, mimetype=f'image/{image_obj.format.lower()}')
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        file_id = file.get('id')
        web_view_link = file.get('webViewLink')
        
        # 4. 권한 설정 (링크가 있는 모든 사용자가 볼 수 있게 - 필수!)
        service.permissions().create(
            fileId=file_id,
            body={'role': 'reader', 'type': 'anyone'}
        ).execute()
        
        return web_view_link
        
    except Exception as e:
        st.error(f"이미지 업로드 실패: {e}")
        return "이미지_없음"

# (B) 학생 명단 불러오기
def load_students_from_sheet():
    client = get_google_sheet_client()
    if not client: return None
    try:
        sheet = client.open("MA학원_DB").worksheet("students")
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except: return None

# (C) 결과 저장하기 (이미지 링크 포함하도록 수정됨)
def save_result_to_sheet(student_name, grade, unit, full_text, image_url):
    client = get_google_sheet_client()
    if not client: return
    try:
        sheet = client.open("MA학원_DB").worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # [날짜, 이름, 학년, 단원, 내용, 이미지주소] 순서로 저장
        sheet.append_row([now, student_name, grade, unit, full_text, image_url])
        
        st.toast("✅ 오답 노트와 문제 사진이 저장되었습니다!", icon="💾")
    except Exception as e:
        st.warning(f"저장 실패: {e}")

# (D) 내 기록 불러오기 (이미지 링크도 가져옴)
def load_my_history(student_name):
    client = get_google_sheet_client()
    if not client: return pd.DataFrame()
    try:
        sheet = client.open("MA학원_DB").worksheet("results")
        data = sheet.get_all_values()
        if not data: return pd.DataFrame()
        
        # 데이터프레임 변환 (컬럼 6개로 확장)
        # 만약 기존 데이터에 이미지 컬럼이 없다면 에러가 날 수 있으니 예외처리 필요
        expected_cols = ["날짜", "이름", "학년", "단원", "내용", "이미지링크"]
        
        # 현재 시트의 컬럼 수에 맞춰서 데이터 가져오기
        df = pd.DataFrame(data, columns=expected_cols[:len(data[0])])
        
        # 내 이름만 필터링
        my_df = df[df['이름'] == student_name]
        
        # 최신순 정렬
        if not my_df.empty:
            my_df = my_df.sort_values(by="날짜", ascending=False)
        return my_df
    except Exception as e:
        # st.error(f"기록 로드 에러: {e}") 
        return pd.DataFrame()

# ----------------------------------------------------------
# [3] 로그인
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
            with st.spinner("확인 중..."):
                df = load_students_from_sheet()
            if df is not None:
                df['id'] = df['id'].astype(str)
                df['pw'] = df['pw'].astype(str)
                user_data = df[df['id'] == user_id]
                if not user_data.empty and user_pw == user_data.iloc[0]['pw']:
                    st.session_state['is_logged_in'] = True
                    st.session_state['user_name'] = user_data.iloc[0]['name']
                    st.rerun()
                else: st.error("정보가 일치하지 않습니다.")
            else: st.error("명단 로드 실패")

if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

# ----------------------------------------------------------
# [4] UI 구성
# ----------------------------------------------------------
with st.sidebar:
    st.success(f"👋 {st.session_state['user_name']} 학생")
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.rerun()
    st.markdown("---")
    
    app_mode = st.radio("메뉴 선택", ["📸 문제 풀기", "📂 오답 복습하기"])
    
    st.markdown("---")
    
    if app_mode == "📸 문제 풀기":
        subject_options = ["초4", "초5", "초6", "중1", "중2", "중3", "공통수학1", "공통수학2", "대수", "미적분1", "수1", "수2", "미적분", "확통"]
        student_grade = st.selectbox("학년/과목", subject_options)
        
        if student_grade in ["초4", "초5", "초6", "중1", "중2"]:
            tone = "친절하고 다정하게, 칭찬과 격려를 많이 해주세요."
        else:
            tone = "엄격하고 건조하게. 팩트와 논리 위주로 설명하세요."

# ----------------------------------------------------------
# [5] 기능 A: 문제 풀기 모드
# ----------------------------------------------------------
if app_mode == "📸 문제 풀기":
    col1, col2 = st.columns([1, 4])
    with col1:
        st.write("🏫")
    with col2:
        st.markdown("### MA학원 AI 오답 도우미")
    
    st.markdown("---")
    
    tab1, tab2 = st.tabs(["📸 카메라", "📂 갤러리"])
    img_file = None
    with tab1: camera_img = st.camera_input("촬영")
    with tab2: uploaded_img = st.file_uploader("파일 선택", type=['jpg', 'png', 'jpeg'])

    if uploaded_img: img_file = uploaded_img
    elif camera_img: img_file = camera_img

    if img_file:
        image = Image.open(img_file)
        st.image(image, caption="선택된 문제", use_container_width=True)

        if st.button("🔍 AI 분석 및 저장", type="primary"):
            with st.spinner("1단계: 문제 분석 중..."):
                try:
                    # 1. AI 분석
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    prompt = f"""
                    [Role] 대치동 20년 경력 1타 강사. 학생: {student_grade}
                    [Output]
                    1. [단원: 대단원>중단원] 표시.
                    2. 출제 의도 1줄 요약.
                    3. 상세 풀이 (말투: {tone}).
                    4. 오답 함정(Tip).
                    5. 쌍둥이 문제 1개 (지문 뒤에 `[[정답_및_해설_시작]]` 넣고 정답 적기).
                    """
                    response = model.generate_content([prompt, image])
                    st.session_state['analysis_result'] = response.text
                except Exception as e:
                    st.error(f"AI 분석 오류: {e}")

            with st.spinner("2단계: 드라이브 업로드 및 기록 중..."):
                try:
                    # 2. 이미지 드라이브 업로드
                    # 파일명 생성: 이름_날짜시간.jpg
                    file_name = f"{st.session_state['user_name']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    image_url = upload_image_to_drive(image, file_name)
                    
                    # 3. 구글 시트 저장
                    unit_name = "미분류"
                    if "[단원:" in response.text:
                        try: unit_name = response.text.split("[단원:")[1].split("]")[0].strip()
                        except: pass
                    
                    save_result_to_sheet(st.session_state['user_name'], student_grade, unit_name, response.text, image_url)
                    
                except Exception as e:
                    st.error(f"저장 오류: {e}")

    # 결과 출력
    if 'analysis_result' in st.session_state:
        st.markdown("### 📝 분석 결과")
        full_text = st.session_state['analysis_result']
        separator = "[[정답_및_해설_시작]]"
        
        if separator in full_text:
            parts = full_text.split(separator)
            st.write(parts[0])
            with st.expander("🔐 쌍둥이 문제 정답 보기"):
                st.write(parts[1])
        else:
            st.write(full_text)

# ----------------------------------------------------------
# [6] 기능 B: 오답 복습 모드 (사진 보기 기능 추가됨!)
# ----------------------------------------------------------
elif app_mode == "📂 오답 복습하기":
    st.header("📂 지난 오답 다시보기")
    
    history_df = load_my_history(st.session_state['user_name'])
    
    if history_df.empty:
        st.info("아직 저장된 오답 노트가 없습니다.")
    else:
        options = history_df.apply(lambda x: f"{x['날짜']} | {x['단원']}", axis=1)
        selected_option = st.selectbox("복습할 기록을 선택하세요:", options)
        
        if selected_option:
            selected_date = selected_option.split(" | ")[0]
            # 해당 날짜 데이터 찾기
            record = history_df[history_df['날짜'] == selected_date].iloc[0]
            
            st.markdown("---")
            col_a, col_b = st.columns([1, 1])
            
            with col_a:
                st.subheader(f"📅 {record['날짜']}")
                st.write(f"**단원:** {record['단원']}")
            
            # 이미지가 있다면 보여주기
            with col_b:
                if "이미지링크" in record and record['이미지링크'].startswith("http"):
                    st.image(record['이미지링크'], caption="당시 문제 사진", use_container_width=True)
                else:
                    st.write("🖼️ 저장된 사진 없음")

            st.markdown("---")
            
            # 저장된 풀이 내용
            saved_text = record['내용']
            separator = "[[정답_및_해설_시작]]"
            
            st.markdown("### 📝 저장된 풀이")
            if separator in saved_text:
                parts = saved_text.split(separator)
                st.write(parts[0])
                with st.expander("🔐 정답 및 해설 다시보기"):
                    st.write(parts[1])
            else:
                st.write(saved_text)

