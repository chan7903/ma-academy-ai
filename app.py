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
# [1] 설정 및 모델명
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫", layout="centered")

# 👇 모델 이름 설정 (현재 가장 안정적인 최신 버전은 1.5-flash 입니다)
# 2.0 버전을 쓰시려면 "gemini-2.0-flash-exp" 라고 적으시면 됩니다.
MODEL_NAME = "gemini-2.5-flash"

# 구글 시트 & 드라이브 ID
SHEET_ID = "1zJ2rs68pSE9Ntesg1kfqlI7G22ovfxX8Fb7v7HgxzuQ"
FOLDER_ID = "1zl6EoXAitDFUWVYoLBtorSJw-JrOm_fG"

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except:
    st.error("Secrets에 GOOGLE_API_KEY가 없습니다.")
    st.stop()

# ----------------------------------------------------------
# [2] 구글 연결 (통합 인증)
# ----------------------------------------------------------
@st.cache_resource
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
        return None

# ----------------------------------------------------------
# [3] 드라이브 기능 (에러 방지 처리됨)
# ----------------------------------------------------------
def upload_image_to_drive(image_file, student_name):
    creds = get_credentials()
    if not creds: return None, None

    try:
        service = build('drive', 'v3', credentials=creds)
        filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{student_name}.jpg"
        
        file_metadata = {'name': filename, 'parents': [FOLDER_ID]}
        media = MediaIoBaseUpload(image_file, mimetype='image/jpeg')
        
        # ⚠️ 여기서 403 오류(용량 부족)가 나면 except로 넘어갑니다.
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink'), file.get('id')
    except Exception as e:
        # 오류가 나도 앱을 죽이지 않고 '실패'라고만 반환
        return "업로드_실패(구글용량제한)", None

def get_image_from_drive(file_id):
    if not file_id or file_id == "None": return None
    creds = get_credentials()
    if not creds: return None
    try:
        service = build('drive', 'v3', credentials=creds)
        request = service.files().get_media(fileId=file_id)
        file = io.BytesIO(request.execute())
        return file
    except:
        return None

# ----------------------------------------------------------
# [4] 시트 데이터 처리
# ----------------------------------------------------------
def save_result_to_sheet(student_name, grade, unit, summary, link, file_id):
    creds = get_credentials()
    if not creds: return
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 👇 [수정됨] summary 길이를 자르지 않고 전체 저장합니다.
        sheet.append_row([now, student_name, grade, unit, summary, link, file_id])
        st.toast("✅ 오답노트 저장 완료!", icon="💾")
    except Exception as e:
        st.error(f"저장 실패: {e}")

def load_user_results(user_name):
    creds = get_credentials()
    if not creds: return pd.DataFrame()
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except:
        return pd.DataFrame()

def load_students_from_sheet():
    creds = get_credentials()
    if not creds: return None
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).worksheet("students")
        return pd.DataFrame(sheet.get_all_records())
    except: return None

# ----------------------------------------------------------
# [5] 로그인 및 세션
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
            else: st.error("명단 로딩 실패")

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

# ==========================================================
# 기능 1: 문제 풀기
# ==========================================================
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
        image_for_view = Image.open(io.BytesIO(img_bytes))
        st.image(image_for_view, caption="선택된 문제")

        if st.button("🔍 1타 강사 분석 시작", type="primary"):
            st.session_state['gemini_image'] = Image.open(io.BytesIO(img_bytes))
            image_for_upload = io.BytesIO(img_bytes)

            # 사진 저장 시도 (실패해도 앱 안 죽게 처리)
            link, file_id = "업로드_실패", None
            try:
                with st.spinner("사진 서버 전송 중... (실패 시 텍스트만 저장됨)"):
                    link, file_id = upload_image_to_drive(image_for_upload, st.session_state['user_name'])
            except:
                pass # 그냥 넘어감

            with st.spinner(f"AI 선생님({MODEL_NAME})이 분석 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    prompt = f"""
                    당신은 대치동 20년 경력의 베테랑 수학 강사입니다. 철저하고 자세히 분석하세요. 
                    학년: {student_grade}, 말투: {tone}
                    
                    [지시사항]
                    1. 첫 줄: [단원: 단원명]
                    2. 풀이: 꼼꼼하고 철저하게. 가독성 좋게 줄바꿈을 자주 하세요.
                    3. 쌍둥이 문제: 1문제 출제.
                    4. **필수:** 쌍둥이 문제 정답과 해설은 맨 마지막에 **===해설===** 구분선 뒤에 작성.
                    """
                    
                    response = model.generate_content([prompt, st.session_state['gemini_image']])
                    st.session_state['analysis_result'] = response.text
                    
                    unit_name = "미분류"
                    if "[단원:" in response.text:
                        try: unit_name = response.text.split("[단원:")[1].split("]")[0].strip()
                        except: pass
                    
                    # 시트 저장 (내용 전체 저장)
                    save_result_to_sheet(
                        st.session_state['user_name'], student_grade, unit_name, 
                        response.text, link, file_id
                    )
                    
                except Exception as e:
                    st.error(f"분석 오류: {e}")

    # 결과 출력 (디자인 개선: 박스 적용)
    if st.session_state['analysis_result']:
        st.markdown("---")
        full_text = st.session_state['analysis_result']
        parts = full_text.split("===해설===")
        
        # 👇 [디자인 개선] 분석 내용을 박스 안에 넣음
        with st.container(border=True):
            st.markdown("### 💡 선생님의 분석")
            st.write(parts[0])
        
        if len(parts) > 1:
            with st.expander("🔐 정답 및 해설 보기 (클릭)"):
                st.write(parts[1])
        
        if st.button("🔄 쌍둥이 문제 추가 생성"):
            with st.spinner("추가 문제 생성 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    extra_prompt = f"위 문제와 난이도가 비슷한 쌍둥이 문제 1개 더. 학년:{student_grade}. 정답은 ===해설=== 뒤에."
                    res = model.generate_content([extra_prompt, st.session_state['gemini_image']])
                    p = res.text.split("===해설===")
                    
                    with st.container(border=True):
                        st.markdown("#### ➕ 추가 문제")
                        st.write(p[0])
                    
                    if len(p) > 1:
                        with st.expander("🔐 정답 보기"):
                            st.write(p[1])
                except Exception as e:
                    st.error(f"오류: {e}")

# ==========================================================
# 기능 2: 오답 노트 보기
# ==========================================================
elif menu == "📒 내 오답 노트":
    st.markdown("### 📒 내 오답 노트 리스트")
    
    with st.spinner("데이터 불러오는 중..."):
        df = load_user_results(st.session_state['user_name'])
    
    if not df.empty and '이름' in df.columns:
        # 내 이름으로 필터링
        my_notes = df[df['이름'] == st.session_state['user_name']]
        
        if not my_notes.empty:
            # 최신순 정렬
            if '날짜' in my_notes.columns:
                my_notes = my_notes.sort_values(by='날짜', ascending=False)
            
            for index, row in my_notes.iterrows():
                # 👇 [디자인 개선] 전체 내용을 박스로 감쌈
                with st.expander(f"📅 {row.get('날짜', '')} - [{row.get('단원', '단원미상')}] 다시보기"):
                    
                    # 1. 텍스트 분석 내용 (전체 내용 표시)
                    with st.container(border=True):
                        st.markdown("**📝 선생님의 분석**")
                        # 내용이 길면 스크롤되거나 전체가 나옴
                        content = row.get('내용', '내용 없음')
                        # ===해설=== 기준으로 잘라서 보여주기
                        if "===해설===" in str(content):
                            c_parts = str(content).split("===해설===")
                            st.write(c_parts[0])
                            if st.button("정답 보기", key=f"ans_{index}"):
                                st.success(c_parts[1])
                        else:
                            st.write(content)

                    # 2. 저장된 사진 불러오기
                    file_id = row.get('파일ID')
                    if not file_id and len(row) > 6: file_id = list(row.values)[6]

                    if file_id and str(file_id) != "None":
                        st.markdown("**🖼️ 내가 틀린 문제 사진**")
                        img_data = get_image_from_drive(file_id)
                        if img_data:
                            st.image(img_data, use_container_width=True)
                        else:
                            st.caption("⚠️ 사진을 불러올 수 없습니다 (구글 권한/용량 문제)")
                    else:
                        st.caption("❌ 사진이 저장되지 않았습니다.")
        else:
            st.info("아직 저장된 오답노트가 없습니다.")
    else:
        st.warning("데이터를 불러올 수 없습니다.")
