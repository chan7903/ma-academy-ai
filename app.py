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
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import os

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

@st.cache_resource
def get_korean_font_path():
    font_file = "NanumGothic.ttf"
    if not os.path.exists(font_file):
        url = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
        try:
            r = requests.get(url)
            with open(font_file, "wb") as f:
                f.write(r.content)
        except: pass
    return font_file

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

# 🔥 [핵심 기능] 오답노트 이미지 생성 (수식 렌더링 포함)
def create_solution_image(original_image, concepts, solution):
    try:
        font_path = get_korean_font_path()
        font_prop = fm.FontProperties(fname=font_path)
        
        # 캔버스 생성
        w, h = original_image.size
        aspect = h / w
        fig_width = 10
        fig_height = fig_width * aspect + 8
        
        fig = plt.figure(figsize=(fig_width, fig_height))
        gs = fig.add_gridspec(2, 1, height_ratios=[aspect, 0.8])
        
        # 1. 이미지 그리기
        ax_img = fig.add_subplot(gs[0])
        ax_img.imshow(original_image)
        ax_img.axis('off')
        
        # 2. 텍스트 그리기
        ax_text = fig.add_subplot(gs[1])
        ax_text.axis('off')
        
        # [수정] $ 기호를 지우지 않고 그대로 둡니다! (Matplotlib이 해석하도록)
        
        # (1) 단원 및 개념 (보라색)
        ax_text.text(0.02, 0.95, f"[단원 및 핵심 개념]\n{concepts}", 
                     fontsize=15, color='purple', fontweight='bold', 
                     va='top', ha='left', wrap=True, fontproperties=font_prop)
        
        # 높이 계산 (줄바꿈 고려)
        line_count = concepts.count('\n') + (len(concepts) // 35) + 3
        offset = line_count * 0.05 
        
        # (2) 풀이 (검은색)
        ax_text.text(0.02, 0.95 - offset, f"[상세 풀이]\n{solution}", 
                     fontsize=13, color='black', 
                     va='top', ha='left', wrap=True, fontproperties=font_prop)

        # 저장
        buf = io.BytesIO()
        plt.savefig(buf, format='jpg', bbox_inches='tight', pad_inches=0.2)
        buf.seek(0)
        plt.close(fig)
        return Image.open(buf)
        
    except Exception as e:
        print(f"이미지 생성 오류: {e}")
        return original_image

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
if 'solution_image' not in st.session_state:
    st.session_state['solution_image'] = None

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
        st.session_state['solution_image'] = None
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
            with st.spinner("1타 강사가 문제를 분석하고 필기하는 중... (잠시만 기다려주세요)"):
                
                resized_image = resize_image(raw_image)
                st.session_state['gemini_image'] = resized_image
                
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    
                    # 🔥 [핵심 수정] 이미지용과 텍스트용 설명을 분리 요청
                    prompt = f"""
                    당신은 대치동 20년 경력 수학 강사입니다. 과목:{selected_subject}, 말투:{tone}
                    
                    [출력 형식 구분자 - 정확히 지킬 것]
                    
                    ===이미지용_개념===
                    (사진 위에 적을 내용입니다. 핵심 개념을 2줄 요약하세요. 수식은 $y=x^2$ 처럼 간단한 LaTeX만 사용하세요.)
                    
                    ===이미지용_풀이===
                    (사진 위에 적을 풀이입니다. 번호를 매겨 핵심만 적으세요. 수식은 $x^2$ 처럼 간단한 LaTeX를 사용하세요. 복잡한 분수나 극한은 피하고 한 줄 수식으로 표현하세요.)
                    
                    ===상세풀이_텍스트===
                    (여기에는 화면 아래에 보여줄 완벽한 풀이를 적으세요. \\begin{{aligned}} 등 복잡한 LaTeX를 마음껏 사용하세요.)
                    
                    ===쌍둥이문제===
                    (쌍둥이 문제 1개. LaTeX 사용)
                    
                    ===정답및해설===
                    (정답 및 해설. LaTeX 사용)
                    """
                    
                    response = model.generate_content([prompt, st.session_state['gemini_image']])
                    st.session_state['analysis_result'] = response.text
                    
                    # 파싱
                    img_concept = "분석 중"
                    img_solution = "분석 중"
                    
                    if "===이미지용_개념===" in response.text:
                        parts = response.text.split("===이미지용_개념===")[1]
                        img_concept = parts.split("===이미지용_풀이===")[0].strip()
                        img_solution = parts.split("===이미지용_풀이===")[1].split("===상세풀이_텍스트===")[0].strip()
                    
                    # 🔥 이미지 생성 (이제 $ 표시가 있어도 지우지 않고 그립니다!)
                    final_image = create_solution_image(st.session_state['gemini_image'], img_concept, img_solution)
                    st.session_state['solution_image'] = final_image 
                    
                    # ImgBB 업로드
                    img_byte_arr = io.BytesIO()
                    final_image.save(img_byte_arr, format='JPEG', quality=90)
                    img_bytes = img_byte_arr.getvalue()
                    
                    link = "이미지_없음"
                    uploaded_link = upload_to_imgbb(img_bytes)
                    if uploaded_link: link = uploaded_link
                    
                    unit_name = img_concept.split("\n")[0][:20]
                    save_result_to_sheet(
                        st.session_state['user_name'], selected_subject, unit_name, 
                        response.text, link
                    )
                    
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"분석 오류: {e}")

    # ------------------------------------------------------
    # [7] 분석 결과 출력
    # ------------------------------------------------------
    if st.session_state['analysis_result']:
        full_text = st.session_state['analysis_result']
        
        parts = {
            "full_solution": "내용 없음", 
            "twin_prob": "내용 없음", 
            "twin_ans": "내용 없음"
        }
        
        if "===상세풀이_텍스트===" in full_text:
            temp = full_text.split("===상세풀이_텍스트===")[1]
            parts["full_solution"] = temp.split("===쌍둥이문제===")[0].strip()
            
            temp = temp.split("===쌍둥이문제===")[1]
            parts["twin_prob"] = temp.split("===정답및해설===")[0].strip()
            parts["twin_ans"] = temp.split("===정답및해설===")[1].strip()

        st.markdown("---")
        
        # 1. 이미지 보여주기 (수식 적용됨!)
        if st.session_state['solution_image']:
            st.markdown("### 📘 오답 분석 결과 (선생님 필기)")
            st.image(st.session_state['solution_image'], caption="AI 선생님의 첨삭 노트", use_container_width=True)
            
            img_byte_arr = io.BytesIO()
            st.session_state['solution_image'].save(img_byte_arr, format='JPEG')
            st.download_button(
                label="📥 오답노트 이미지 다운로드",
                data=img_byte_arr.getvalue(),
                file_name=f"오답노트_{st.session_state['user_name']}.jpg",
                mime="image/jpeg"
            )
            
        # 2. 하단 텍스트 (완벽한 상세 풀이)
        with st.expander("📜 상세 풀이 텍스트로 보기 (복잡한 수식 포함)"):
            st.markdown(parts["full_solution"])

        # 3. 쌍둥이 문제
        st.markdown("### 📝 쌍둥이 문제")
        st.write(parts["twin_prob"])
        
        with st.expander("🔐 정답 및 해설 보기"):
            st.write(parts["twin_ans"])
        
        if st.button("🔄 쌍둥이 문제 추가 생성"):
            with st.spinner("추가 문제 생성 중..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    extra_prompt = f"쌍둥이 문제 1개 더. 과목:{selected_subject}. 수식은 반드시 LaTeX($) 사용. 정답은 ===해설=== 뒤에."
                    res = model.generate_content([extra_prompt, st.session_state['gemini_image']])
                    
                    p_text = res.text
                    p_prob = ""
                    p_ans = ""
                    if "===해설===" in p_text:
                        p_prob = p_text.split("===해설===")[0].strip()
                        p_ans = p_text.split("===해설===")[1].strip()
                    else:
                        p_prob = p_text

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
                    img_link = row.get('링크')
                    if img_link and str(img_link).startswith('http'):
                        st.image(img_link, caption="첨삭된 오답노트", use_container_width=True)
                    else:
                        st.caption("이미지 없음")

                    content = row.get('내용', '내용 없음')
                    if "===상세풀이_텍스트===" in str(content):
                         try:
                             c_sol = content.split("===상세풀이_텍스트===")[1].split("===쌍둥이문제===")[0].strip()
                             st.markdown("**💡 상세 풀이**")
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
        else: st.info("오답노트가 없습니다.")
    else: st.warning("데이터 로딩 실패")
