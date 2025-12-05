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

# ==========================================================
# 🛑 [필수 설정] 폴더 ID 및 시트 ID 설정
# ==========================================================
# 원장님이 주신 ID에서 뒤에 ?hl=ko 같은 잡동사니는 뺐습니다. (그래야 작동합니다)
DRIVE_FOLDER_ID = "1zl6EoXAitDFUWVYoLBtorSJw-JrOm_fG"
SHEET_ID = "1zJ2rs68pSE9Ntesg1kfqlI7G22ovfxX8Fb7v7HgxzuQ"

# ==========================================================
# [1] 기본 설정 및 인증
# ==========================================================
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫")

# 1. Gemini API 인증
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except:
    st.error("오류: Secrets에 GOOGLE_API_KEY가 없습니다.")
    st.stop()

# 2. 구글 클라우드(시트+드라이브) 인증
def get_gcp_creds():
    try:
        # Secrets에서 서비스 계정 정보 가져오기
        secrets = st.secrets["gcp_service_account"]
        
        # 권한 범위: 구글 시트 + 구글 드라이브 모두 사용
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(secrets, scopes=scopes)
        return creds
    except Exception as e:
        st.error(f"구글 계정 인증 실패: {e}")
        return None

# ==========================================================
# [2] 기능 함수 (업로드, 읽기, 쓰기)
# ==========================================================

# A. 이미지를 구글 드라이브에 올리는 함수
def upload_image_to_drive(image_file, student_name):
    creds = get_gcp_creds()
    if not creds: return None
    
    try:
        # 구글 드라이브 도구 준비
        service = build('drive', 'v3', credentials=creds)
        
        # 파일 이름 만들기 (예: 20240520_143000_김철수.jpg)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"{timestamp}_{student_name}.jpg"
        
        # 이미지를 업로드 가능한 형태로 변환
        img_byte_arr = io.BytesIO()
        image = Image.open(image_file)
        
        # 이미지 포맷에 따라 저장 (PNG, JPG 등)
        if image.format:
            fmt = image.format
        else:
            fmt = 'JPEG'
            
        image.save(img_byte_arr, format=fmt)
        img_byte_arr.seek(0) # 파일 포인터 초기화
        
        # 메타데이터 (어느 폴더에 넣을지)
        file_metadata = {
            'name': file_name,
            'parents': [DRIVE_FOLDER_ID] 
        }
        
        media = MediaIoBaseUpload(img_byte_arr, mimetype=f'image/{fmt.lower()}')
        
        # 실제 업로드 실행
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        # 업로드된 파일의 보기 링크(URL) 반환
        return file.get('webViewLink')
        
    except Exception as e:
        st.error(f"이미지 업로드 실패: {e}")
        return "업로드_오류"

# B. 학생 명단 불러오기 (구글 시트)
def load_students_from_sheet():
    creds = get_gcp_creds()
    if not creds: return None
    
    try:
        client = gspread.authorize(creds)
        # students 시트 불러올 때 (들여쓰기 수정됨)
        sheet = client.open_by_key(SHEET_ID).worksheet("students")
        return pd.DataFrame(sheet.get_all_records())
    except Exception as e:
        st.error(f"학생 명단 로딩 실패: {e}")
        return None

# C. 분석 결과 및 링크 저장하기 (구글 시트)
def save_result_to_sheet(student_name, grade, unit, summary, image_link):
    creds = get_gcp_creds()
    if not creds: return
    
    try:
        client = gspread.authorize(creds)
        # results 시트 불러올 때 (들여쓰기 수정됨)
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # [날짜, 이름, 학년, 단원, 내용, 이미지링크] 순서로 저장
        sheet.append_row([now, student_name, grade, unit, summary, image_link])
        st.toast("✅ 구글 시트와 드라이브에 저장 완료!", icon="💾")
    except Exception as e:
        st.error(f"데이터 저장 실패: {e}")

# ==========================================================
# [3] 로그인 화면
# ==========================================================
if 'is_logged_in' not in st.session_state:
    st.session_state['is_logged_in'] = False
    st.session_state['user_name'] = None

if not st.session_state['is_logged_in']:
    st.markdown("<h1 style='text-align: center;'>🔒 MA학원 로그인</h1>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        user_id = st.text_input("아이디")
        user_pw = st.text_input("비밀번호", type="password")
        
        if st.button("로그인", use_container_width=True):
            with st.spinner("확인 중..."):
                df = load_students_from_sheet()
                
            if df is not None:
                # 데이터 타입 통일 (문자열)
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
                    st.error("없는 아이디입니다.")
            else:
                st.error("DB 연결에 실패했습니다.")
    st.stop()

# ==========================================================
# [4] 메인 앱 화면
# ==========================================================
with st.sidebar:
    st.success(f"👋 안녕, {st.session_state['user_name']}!")
    if st.button("로그아웃"):
        st.session_state['is_logged_in'] = False
        st.rerun()
        
    st.markdown("---")
    st.header("설정")
    grade_options = ["초4", "초5", "초6", "중1", "중2", "중3", "고1(공통)", "고2(수1/2)", "고3(미적/확통)"]
    student_grade = st.selectbox("학년", grade_options)
    
    # 말투 설정
    if any(x in student_grade for x in ["초", "중1", "중2"]):
        tone_instruction = "친절하고 다정하게, 용기를 북돋아주는 말투로 설명해."
    else:
        tone_instruction = "엄격하고 건조하게, 핵심만 짚어서 논리적으로 설명해."

col1, col2 = st.columns([1, 4])
with col1:
    try: st.image("logo.png", use_container_width=True)
    except: st.write("🏫")
with col2:
    st.markdown("### 🏫 MA학원 AI 오답 도우미")

st.info("문제를 찍으면 [풀이]해주고 [구글 드라이브]에 원본을 저장합니다.")

# ----------------------------------------------------------
# [5] 문제 업로드 및 실행
# ----------------------------------------------------------
tab1, tab2 = st.tabs(["📸 카메라", "📂 갤러리"])
img_file = None

with tab1:
    cam = st.camera_input("문제 촬영")
    if cam: img_file = cam
with tab2:
    up = st.file_uploader("파일 선택", type=['jpg', 'png'])
    if up: img_file = up

if img_file:
    # 미리보기
    image = Image.open(img_file)
    st.image(image, caption="선택된 문제")
    
    if st.button("🚀 분석 및 저장 시작", type="primary"):
        
        # 1. 이미지 업로드 (드라이브)
        image_link = "저장안함"
        with st.spinner("1/2단계: 구글 드라이브에 사진 저장 중..."):
            image_link = upload_image_to_drive(img_file, st.session_state['user_name'])
            
            if image_link == "업로드_오류" or not image_link:
                st.error("사진 저장 실패 (폴더 ID 확인 필요)")
                image_link = "저장실패"
            else:
                st.success("사진 저장 완료!")

        # 2. AI 분석 (Gemini)
        with st.spinner("2/2단계: 대치동 1타 강사 빙의 중..."):
            try:
                # 원장님이 원하시는 모델 (2.5 Flash) 적용
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                prompt = f"""
                [Role] 대치동 20년 경력 1타 강사. 철저하게 분석하세요. 
                학생 학년: {student_grade}
                
                [Output]
                1. [단원: 대단원>중단원] 표시.
                2. 출제 의도 1줄 요약.
                3. 상세 풀이 (말투: {tone_instruction})
                4. 오답 함정(Tip).
                5. 쌍둥이 문제 1개 (지문 뒤에 `[[정답_및_해설_시작]]` 넣고 정답 적기).
                """
                
                response = model.generate_content([prompt, image])
                result_text = response.text  
                
                st.markdown("### 📝 분석 결과")
                st.write(result_text)
                
                # 단원명 추출 로직
                unit_name = "미분류"
                if "[단원:" in result_text:
                    try:
                        unit_name = result_text.split("[단원:")[1].split("]")[0].strip()
                    except: pass
                
                # 3. 구글 시트 저장
                save_result_to_sheet(
                    st.session_state['user_name'],
                    student_grade,
                    unit_name,
                    result_text[:300] + "...", 
                    image_link 
                )
                
            except Exception as e:
                st.error(f"분석 중 오류 발생: {e}")
