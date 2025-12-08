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
# [2] 유틸리티 함수
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

def resize_image(image, max_width=800):
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
        response = requests.post(url, data=payload, timeout=15)
        if response.status_code == 200:
            return response.json()['data']['url']
        return None
    except: return None

def save_result_to_sheet(student_name, subject, unit, summary, link):
    client = get_sheet_client()
    if not client: return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("results")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([now, student_name, subject, unit, summary, link, "", 0])
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
        subject_options = [
            "초4 수학", "초5 수학", "초6 수학",
            "중1 수학", "중2 수학", "중3 수학",
            "--- 2022 개정 (현 고1) ---",
            "[22개정] 공통수학1", "[22개정] 공통수학2", "[22개정] 대수", "[22개정] 미적분1", "[22개정] 확통",
            "--- 2015 개정 (현 고2/3) ---",
            "[15개정] 수학(상/하)", "[15개정] 수1", "[15개정] 수2", "[15개정] 미적분", "[15개정] 확통", "[15개정] 기하"
        ]
        selected_subject = st.selectbox("과목 선택", subject_options)
        
        if "---" in selected_subject:
            st.warning("⚠️ 과목을 선택해주세요.")
            st.stop()

        if any(x in selected_subject for x in ["초", "중1", "중2"]):
            tone = "친절하고 상세하게"
        else:
            tone = "엄격하고 간결하게, 수식 위주로"

    st.markdown("### 🏫 MA학원 AI 오답 도우미")

    tab1, tab2 = st.tabs(["📸 카메라", "📂 갤러리"])
    img_file = None
    with tab1:
        cam = st.camera_input("촬영")
        if cam: img_file = cam
    with tab2:
        up = st.file_uploader("파일 선택", type=['jpg', 'png', 'jpeg'])
        if up: img_file = up

    if img_file:
        try:
            raw_image = Image.open(img_file)
            if raw_image.mode in ("RGBA", "P"): raw_image = raw_image.convert("RGB")
            st.image(raw_image, caption="선택된 문제", width=400)
        except:
            st.error("이미지 오류")
            st.stop()

        if st.button("🔍 1타 강사 분석 시작", type="primary"):
            with st.spinner("1타 강사가 문제를 분석하고 있습니다..."):
                
                # 1. 이미지 처리
                resized_image = resize_image(raw_image)
                st.session_state['gemini_image'] = resized_image
                
                img_byte_arr = io.BytesIO()
                resized_image.save(img_byte_arr, format='JPEG', quality=85)
                img_bytes = img_byte_arr.getvalue()
                
                # 2. ImgBB 업로드
                link = "이미지_없음"
                uploaded_link = upload_to_imgbb(img_bytes)
                if uploaded_link: link = uploaded_link

                # 3. AI 분석 (구분자 사용)
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    
                    # 🔥 [수정] 프롬프트: 구분자를 사용하여 영역을 확실히 나눔
                    prompt = f"""
                    당신은 대치동 20년 경력 수학 강사입니다. 과목:{selected_subject}, 말투:{tone}
                    
                    [출력 형식]
                    아래 구분자를 사용하여 4가지 영역을 정확히 나눠서 출력하세요.
                    
                    ===단원및개념===
                    (이 문제의 단원명과 풀이에 꼭 필요한 핵심 개념이나 공식을 간단히 적으세요)
                    
                    ===풀이===
                    (과도한 친절함이나 불필요한 말은 빼고, 수식 위주로 간결하고 논리적으로 설명하세요. 논리적 비약이 없도록 연결어는 자연스럽게 쓰세요.)
                    
                    ===쌍둥이문제===
                    (위 문제와 단원 및 풀이 논리가 같은 문제를 하나 만드세요)
                    
                    ===정답및해설===
                    (쌍둥이 문제의 정답과 상세 해설을 적으세요)
                    """
                    
                    response = model.generate_content([prompt, st.session_state['gemini_image']])
                    st.session_state['analysis_result'] = response.text
                    
                    unit_name = "미분류"
                    if "===단원및개념===" in response.text:
                        try: 
                            # 단원명 추출 시도 (첫 줄)
                            section = response.text.split("===단원및개념===")[1].split("===")[0].strip()
                            unit_name = section.split("\n")[0]
                        except: pass
                    
                    save_result_to_sheet(
                        st.session_state['user_name'], selected_subject, unit_name, 
                        response.text, link
                    )
                    
                    # 🔥 [핵심] 분석이 끝나면 즉시 화면을 새로고침하여 결과를 깔끔하게 보여줌 (중복 제거)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"분석 오류: {e}")

    # ------------------------------------------------------
    # [7] 분석 결과 출력 (여기가 최종 화면)
    # ------------------------------------------------------
    if st.session_state['analysis_result']:
        full_text = st.session_state['analysis_result']
        
        # 구분자로 텍스트 나누기
        # 만약 구분자가 제대로 안 나왔을 때를 대비해 기본값 처리
        parts = {
            "concepts": "분석 내용 없음",
            "solution": "분석 내용 없음",
            "twin_prob": "생성 실패",
            "twin_ans": "생성 실패"
        }
        
        try:
            # 파싱 로직
            if "===단원및개념===" in full_text:
                temp = full_text.split("===단원및개념===")[1]
                parts["concepts"] = temp.split("===풀이===")[0].strip()
                
                temp = temp.split("===풀이===")[1]
                parts["solution"] = temp.split("===쌍둥이문제===")[0].strip()
                
                temp = temp.split("===쌍둥이문제===")[1]
                parts["twin_prob"] = temp.split("===정답및해설===")[0].strip()
                
                parts["twin_ans"] = temp.split("===정답및해설===")[1].strip()
        except:
            parts["solution"] = full_text # 파싱 실패 시 통으로 보여줌

        st.markdown("---")
        
        # 1. 단원 및 개념 (눌러야 나옴)
        with st.expander("📘 단원 및 핵심 개념 확인하기"):
            st.info(parts["concepts"])
            
        # 2. 풀이 (간결한 수식 위주, 바로 보임)
        with st.container(border=True):
            st.markdown("### 💡 선생님의 풀이")
            st.write(parts["solution"])
            
        # 3. 쌍둥이 문제 (바로 보임)
        st.markdown("### 📝 쌍둥이 문제")
        st.write(parts["twin_prob"])
        
        # 4. 정답 및 해설 (눌러야 나옴)
        with st.expander("🔐 정답 및 해설 보기"):
            st.write(parts["twin_ans"])
        
        # 5. 추가 생성 버튼
        if st.button("🔄 쌍둥이 문제 추가 생성"):
            with st.spinner("추가 문제 생성 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    extra_prompt = f"""
                    위 문제와 동일한 단원의 쌍둥이 문제 1개를 더 만드세요.
                    형식:
                    ===쌍둥이문제===
                    (문제 내용)
                    ===정답및해설===
                    (정답 및 해설)
                    """
                    res = model.generate_content([extra_prompt, st.session_state['gemini_image']])
                    
                    # 추가 문제 파싱 및 출력
                    p_text = res.text
                    p_prob = "생성 실패"
                    p_ans = "생성 실패"
                    
                    if "===쌍둥이문제===" in p_text:
                        temp = p_text.split("===쌍둥이문제===")[1]
                        p_prob = temp.split("===정답및해설===")[0].strip()
                        p_ans = temp.split("===정답및해설===")[1].strip()
                    
                    st.markdown("#### ➕ 추가 문제")
                    st.write(p_prob)
                    with st.expander("🔐 정답 보기"):
                        st.write(p_ans)
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
                label = f"📅 {row.get('날짜', '')} | [{row.get('과목', '과목미상')}] | 🔁 복습 {review_cnt}회"
                
                with st.expander(label):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        # 오답노트에서도 파싱해서 보여주기 시도
                        content = row.get('내용', '내용 없음')
                        if "===단원및개념===" in str(content):
                            try:
                                c_con = content.split("===단원및개념===")[1].split("===풀이===")[0]
                                c_sol = content.split("===풀이===")[1].split("===쌍둥이문제===")[0]
                                
                                st.caption("📘 핵심 개념")
                                st.write(c_con)
                                st.markdown("**💡 풀이**")
                                st.write(c_sol)
                            except: st.write(content)
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
