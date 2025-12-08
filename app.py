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

# ----------------------------------------------------------
# [1] 기본 설정
# ----------------------------------------------------------
st.set_page_config(page_title="MA학원 AI 오답 도우미", page_icon="🏫", layout="centered")

MODEL_NAME = "gemini-2.5-flash"
SHEET_ID = "1zJ2rs68pSE9Ntesg1kfqlI7G22ovfxX8Fb7v7HgxzuQ"

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    IMGBB_API_KEY = st.secrets["IMGBB_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
except:
    st.error("설정 오류: Secrets 키 확인 필요")
    st.stop()

# ----------------------------------------------------------
# [2] 유틸리티 함수 (시트, 이미지)
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

# 👇 [속도 개선 1] 이미지 크기 줄이는 함수 추가
def resize_image(image, max_width=1024):
    w, h = image.size
    if w > max_width:
        ratio = max_width / float(w)
        new_h = int((float(h) * float(ratio)))
        image = image.resize((max_width, new_h), Image.Resampling.LANCZOS)
    return image

def upload_to_imgbb(image_bytes):
    url = "https://api.imgbb.com/1/upload"
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"key": IMGBB_API_KEY, "image": encoded_image}
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            return response.json()['data']['url']
        return None
    except: return None

def save_result_to_sheet(student_name, grade, unit, summary, link):
    client = get_sheet_client()
    if not client: return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([now, student_name, grade, unit, summary, link, "", 0])
        st.toast("✅ 저장 완료!", icon="💾")
    except: pass

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
    if not client: return None
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("students")
        return pd.DataFrame(sheet.get_all_records())
    except: return None

# ----------------------------------------------------------
# [3] 로그인
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
            else: st.error("접속 실패")

if not st.session_state['is_logged_in']:
    login_page()
    st.stop()

# ----------------------------------------------------------
# [4] 메인 화면
# ----------------------------------------------------------
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
        student_grade = st.selectbox("학년", ["초4", "초5", "초6", "중1", "중2", "중3", "고1", "고2", "고3"])
        tone = "친절하게" if any(x in student_grade for x in ["초", "중1", "중2"]) else "엄격하게"

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
        # 이미지 열기 및 리사이징 (속도 개선 핵심!)
        raw_image = Image.open(img_file)
        resized_image = resize_image(raw_image) # 1024px로 줄임
        
        # 리사이징된 이미지를 다시 바이트로 변환 (API 전송용)
        img_byte_arr = io.BytesIO()
        resized_image.save(img_byte_arr, format=raw_image.format if raw_image.format else 'JPEG')
        img_bytes = img_byte_arr.getvalue()

        st.image(resized_image, caption="선택된 문제", width=400)

        if st.button("🔍 1타 강사 분석 시작", type="primary"):
            st.session_state['gemini_image'] = resized_image
            
            # ImgBB 업로드 (백그라운드 처리 느낌으로)
            link = "이미지_없음"
            with st.spinner("서버 연결 중..."):
                uploaded_link = upload_to_imgbb(img_bytes)
                if uploaded_link: link = uploaded_link

            # 👇 [속도 개선 2] 스트리밍 방식으로 변경!
            st.markdown("---")
            result_container = st.empty() # 결과가 들어갈 빈 상자
            full_response = ""
            
            try:
                model = genai.GenerativeModel(MODEL_NAME)
                prompt = f"""
                대치동 20년 경력 수학 강사. 학년:{student_grade}, 말투:{tone}
                1. [단원: 단원명]
                2. 꼼꼼한 풀이.
                3. 쌍둥이 문제 1개. **정답은 맨 뒤에 ===해설=== 구분선 넣고 작성.**
                """
                
                # stream=True 옵션 사용
                response_stream = model.generate_content([prompt, st.session_state['gemini_image']], stream=True)
                
                # 한 글자씩 받아오며 화면에 뿌리기
                for chunk in response_stream:
                    full_response += chunk.text
                    result_container.markdown(full_response)
                
                # 분석 끝난 후 세션 및 시트 저장
                st.session_state['analysis_result'] = full_response
                
                unit_name = "미분류"
                if "[단원:" in full_response:
                    try: unit_name = full_response.split("[단원:")[1].split("]")[0].strip()
                    except: pass
                
                save_result_to_sheet(
                    st.session_state['user_name'], student_grade, unit_name, 
                    full_response, link
                )
                
            except Exception as e:
                st.error(f"분석 오류: {e}")

    # 결과가 이미 있으면 보여주기 (새로고침 시)
    if st.session_state['analysis_result']:
        # 방금 스트리밍으로 보여줬더라도, 버튼 클릭 등으로 리셋될 수 있으니 다시 그려줌
        full_text = st.session_state['analysis_result']
        parts = full_text.split("===해설===")
        
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
                    extra_prompt = f"쌍둥이 문제 1개 더. 학년:{student_grade}. 정답은 ===해설=== 뒤에."
                    
                    # 추가 생성도 스트리밍 적용
                    res_stream = model.generate_content([extra_prompt, st.session_state['gemini_image']], stream=True)
                    extra_full = ""
                    extra_container = st.empty()
                    
                    for chunk in res_stream:
                        extra_full += chunk.text
                        extra_container.markdown(extra_full)
                    
                    # 스트리밍 끝나면 깔끔하게 다시 포맷팅
                    extra_container.empty()
                    p = extra_full.split("===해설===")
                    
                    with st.container(border=True):
                        st.markdown("#### ➕ 추가 문제")
                        st.write(p[0])
                    
                    if len(p) > 1:
                        with st.expander("🔐 정답 보기"):
                            st.write(p[1])
                            
                except Exception as e:
                    st.error(f"오류: {e}")

elif menu == "📒 내 오답 노트":
    st.markdown("### 📒 내 오답 노트 리스트")
    st.caption("복습 완료 버튼을 눌러보세요!")
    
    with st.spinner("로딩 중..."):
        df = load_user_results(st.session_state['user_name'])
    
    if not df.empty and '이름' in df.columns:
        my_notes = df[df['이름'] == st.session_state['user_name']]
        if not my_notes.empty:
            if '날짜' in my_notes.columns:
                my_notes = my_notes.sort_values(by='날짜', ascending=False)
            
            for index, row in my_notes.iterrows():
                review_cnt = row.get('복습횟수')
                if review_cnt == '' or review_cnt is None: review_cnt = 0
                label = f"📅 {row.get('날짜', '')} | [{row.get('단원', '단원미상')}] | 🔁 복습 {review_cnt}회"
                
                with st.expander(label):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        with st.container(border=True):
                            content = row.get('내용', '내용 없음')
                            if "===해설===" in str(content):
                                c_parts = str(content).split("===해설===")
                                st.write(c_parts[0])
                                if st.button("정답 보기", key=f"ans_{index}"):
                                    st.info(c_parts[1])
                            else:
                                st.write(content)
                        if st.button("✅ 복습 완료", key=f"rev_{index}"):
                            if increment_review_count(row.get('날짜'), row.get('이름')):
                                st.toast("복습 횟수 증가!")
                                import time
                                time.sleep(0.5)
                                st.rerun()
                    with col2:
                        img_link = row.get('링크')
                        if img_link and str(img_link).startswith('http'):
                            st.image(img_link, caption="원본 문제", use_container_width=True)
                        else: st.caption("이미지 없음")
        else: st.info("오답노트가 없습니다.")
    else: st.warning("데이터 로딩 실패")
