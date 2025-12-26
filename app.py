import streamlit as st
import google.generativeai as genai
from PIL import Image
import io
import time

# ----------------------------------------------------------
# [1] 기본 설정 & 디자인 주입 (HTML 파일 스타일 적용)
# ----------------------------------------------------------
st.set_page_config(page_title="MathAI Pro", page_icon="🏫", layout="wide")

# API 키 설정 (기존에 쓰시던 키를 여기에 입력하거나 secrets에 저장하세요)
try:
    # st.secrets를 사용하거나 직접 키를 입력하세요
    # genai.configure(api_key="여기에_API_KEY_입력") 
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except:
    pass

# 🔥 핵심: Tailwind CSS 및 폰트, 커스텀 스타일 주입
st.markdown("""
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined" rel="stylesheet" />
    
    <style>
        /* Streamlit 기본 UI 숨기기 및 배경 설정 */
        .stApp {
            background-color: #f6f7f8; /* 배경색: HTML 파일의 background-light */
            font-family: 'Lexend', 'Noto Sans KR', sans-serif;
        }
        header {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container {
            padding-top: 0rem !important;
            padding-bottom: 0rem !important;
            padding-left: 0rem !important;
            padding-right: 0rem !important;
            max-width: 100% !important;
        }
        
        /* Streamlit 위젯 커스텀 스타일링 */
        /* 버튼을 오렌지색(Primary)으로 변경 */
        div.stButton > button {
            background-color: #f97316 !important;
            color: white !important;
            border: none !important;
            border-radius: 0.5rem !important;
            padding: 0.75rem 1rem !important;
            font-weight: 700 !important;
            width: 100%;
            transition: all 0.2s;
        }
        div.stButton > button:hover {
            background-color: #ea580c !important; /* 호버 시 진한 오렌지 */
            transform: scale(0.98);
        }
        
        /* 파일 업로더 디자인 */
        [data-testid="stFileUploader"] {
            background-color: white;
            padding: 20px;
            border-radius: 12px;
            border: 1px dashed #cbd5e1;
        }

        /* 커스텀 카드 클래스 (HTML 재현용) */
        .math-card {
            background-color: white;
            border-radius: 0.75rem; /* rounded-xl */
            border: 1px solid #e5e7eb;
            box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }
        .section-title {
            font-size: 1.5rem;
            font-weight: 800;
            color: #111418;
            letter-spacing: -0.025em;
        }
    </style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# [2] 헤더 영역 (HTML 코드 그대로 활용)
# ----------------------------------------------------------
st.markdown("""
<header class="sticky top-0 z-50 bg-white border-b border-gray-200 px-6 py-3 shadow-sm mb-6">
    <div class="max-w-[1440px] mx-auto flex items-center justify-between">
        <div class="flex items-center gap-4">
            <div class="w-8 h-8 text-[#f97316] flex items-center justify-center">
                <span class="material-symbols-outlined" style="font-size: 32px;">calculate</span>
            </div>
            <h2 class="text-xl font-bold tracking-tight text-slate-900">MathAI <span class="text-[#f97316]">Pro</span></h2>
        </div>
        <nav class="hidden md:flex flex-1 justify-center gap-8">
            <a class="text-slate-600 hover:text-[#f97316] text-sm font-medium transition-colors cursor-pointer">대시보드</a>
            <a class="text-slate-600 hover:text-[#f97316] text-sm font-medium transition-colors cursor-pointer">내 문제집</a>
            <a class="text-[#f97316] font-bold text-sm transition-colors cursor-pointer border-b-2 border-[#f97316]">오답 노트</a>
        </nav>
        <div class="flex items-center gap-4">
            <div class="bg-gray-100 rounded-full w-9 h-9 flex items-center justify-center border border-gray-200">
                <span class="material-symbols-outlined text-gray-500">person</span>
            </div>
        </div>
    </div>
</header>
""", unsafe_allow_html=True)

# ----------------------------------------------------------
# [3] 메인 레이아웃 (Grid 시스템)
# ----------------------------------------------------------

# 중앙 정렬을 위한 컨테이너
col_spacer1, col_main, col_spacer2 = st.columns([1, 10, 1])

with col_main:
    # 상단 타이틀 영역
    st.markdown("""
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-end gap-4 mb-6">
        <div class="flex flex-col gap-1">
            <h1 class="section-title">새 문제 추가 & 분석</h1>
            <p class="text-slate-500 text-sm">AI가 손글씨를 분석하여 정석 풀이와 숏컷을 제공합니다.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 2단 레이아웃 (왼쪽: 입력 / 오른쪽: 결과)
    left_col, right_col = st.columns([1, 1.2], gap="large")

    # [왼쪽 칼럼] 문제 입력 카드
    with left_col:
        st.markdown('<div class="math-card h-full">', unsafe_allow_html=True)
        
        # 탭 메뉴 디자인
        st.markdown("""
        <div class="flex border-b border-gray-100 mb-6">
            <button class="flex-1 pb-3 border-b-2 border-[#f97316] text-[#f97316] font-bold text-sm flex items-center justify-center gap-2">
                <span class="material-symbols-outlined">photo_camera</span> 스캔 / 업로드
            </button>
            <button class="flex-1 pb-3 text-gray-400 font-medium text-sm flex items-center justify-center gap-2">
                <span class="material-symbols-outlined">edit</span> 필기 입력
            </button>
        </div>
        """, unsafe_allow_html=True)

        # Streamlit 파일 업로더
        st.write("📸 **문제 사진을 올려주세요**")
        uploaded_file = st.file_uploader("이미지 업로드", type=['png', 'jpg', 'jpeg'], label_visibility="collapsed")
        
        # 과목 선택
        st.write("📚 **과목 선택**")
        subject = st.selectbox("과목", ["고1 공통수학", "수학 I", "수학 II", "미적분", "확률과 통계"], label_visibility="collapsed")

        if uploaded_file:
            # 이미지 미리보기 (Tailwind 스타일 적용)
            st.markdown('<div class="mt-4 rounded-lg overflow-hidden border border-gray-200">', unsafe_allow_html=True)
            st.image(uploaded_file, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # 분석 버튼 (CSS로 오렌지색 스타일링 됨)
            if st.button("✨ AI 분석 시작하기", type="primary"):
                with st.spinner("AI 선생님이 문제를 분석 중입니다..."):
                    try:
                        # ----------------------------------------------------
                        # [AI 로직 연결 부분] 원장님의 AI 코드가 실행되는 곳
                        # ----------------------------------------------------
                        image = Image.open(uploaded_file)
                        
                        # (테스트용 더미 데이터 - 실제 AI 연결 시 이 부분을 genai 호출로 교체하세요)
                        # response = model.generate_content([prompt, image]) 
                        time.sleep(2) # 분석하는 척
                        
                        # AI 결과 저장 (세션 상태 사용)
                        st.session_state['ai_result'] = {
                            "formula": "2x² + 5x - 3 = 0",
                            "concept": "이차방정식의 인수분해",
                            "solution": """
                            1. 인수분해를 시도합니다: (2x - 1)(x + 3) = 0
                            2. 각 인수를 0으로 둡니다: 2x = 1 또는 x = -3
                            3. 정답: x = 1/2 또는 x = -3
                            """,
                            "shortcut": "상수항 -3의 약수와 최고차항 2의 약수를 이용해 빠르게 대입해 봅니다.",
                            "wrong_reason": "부호 실수 주의: 인수분해 과정에서 +3을 -3으로 착각하기 쉽습니다."
                        }
                    except Exception as e:
                        st.error(f"오류 발생: {e}")

        st.markdown('</div>', unsafe_allow_html=True) # 카드 닫기

    # [오른쪽 칼럼] 결과 출력 카드
    with right_col:
        # 결과가 있을 때만 표시
        if 'ai_result' in st.session_state:
            res = st.session_state['ai_result']
            
            # 1. 수식 인식 결과 카드
            st.markdown(f"""
            <div class="math-card">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="font-bold text-slate-800 flex items-center gap-2">
                        <span class="material-symbols-outlined text-[#f97316]">auto_awesome</span>
                        AI 인식 결과
                    </h3>
                    <span class="text-xs font-bold text-green-600 bg-green-100 px-2 py-1 rounded-full">정확도 높음</span>
                </div>
                <div class="bg-gray-50 rounded-lg p-6 flex items-center justify-center border border-gray-200">
                    <p class="text-2xl font-serif italic text-slate-800">{res['formula']}</p>
                </div>
                <p class="text-xs text-slate-500 mt-2 flex items-center gap-1">
                    <span class="material-symbols-outlined text-[14px]">info</span>
                    AI가 손글씨를 수식으로 변환했습니다.
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            # 2. 상세 풀이 카드
            st.markdown(f"""
            <div class="math-card">
                <h4 class="font-bold text-sm text-slate-500 mb-3 uppercase tracking-wider">상세 풀이 과정</h4>
                <div class="space-y-4 pl-4 border-l-2 border-gray-100">
                    <div class="relative">
                        <div class="absolute -left-[21px] top-1 bg-green-500 rounded-full w-2.5 h-2.5 outline outline-4 outline-white"></div>
                        <p class="font-bold text-sm text-slate-800 mb-1">핵심 개념: {res['concept']}</p>
                        <div class="text-sm text-slate-600 leading-relaxed whitespace-pre-line">{res['solution']}</div>
                    </div>
                     <div class="relative mt-6">
                        <div class="absolute -left-[21px] top-1 bg-[#f97316] rounded-full w-2.5 h-2.5 outline outline-4 outline-white"></div>
                        <p class="font-bold text-sm text-[#f97316] mb-1">⚡ 1타 강사 숏컷</p>
                        <p class="text-sm text-slate-700 bg-orange-50 p-3 rounded-lg border border-orange-100">{res['shortcut']}</p>
                    </div>
                </div>
                
                <div class="mt-6 pt-4 border-t border-gray-100">
                    <p class="text-sm font-bold text-red-500 mb-2 flex items-center gap-1">
                        <span class="material-symbols-outlined text-sm">warning</span> 선생님의 첨삭 노트
                    </p>
                    <p class="text-sm text-slate-600">{res['wrong_reason']}</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # 하단 액션 버튼
            col_act1, col_act2 = st.columns(2)
            with col_act1:
                st.button("💾 오답노트 저장", key="save_btn")
            with col_act2:
                st.button("🔄 유사 문제 생성", key="similar_btn")
                
        else:
            # 대기 화면 (Stitch 디자인 참고)
            st.markdown("""
            <div class="math-card flex flex-col items-center justify-center text-center h-full min-h-[400px]">
                <div class="w-20 h-20 bg-gray-50 rounded-full flex items-center justify-center mb-4">
                    <span class="material-symbols-outlined text-gray-300 text-[40px]">fact_check</span>
                </div>
                <h3 class="text-lg font-bold text-slate-700 mb-2">분석 대기 중</h3>
                <p class="text-slate-500 text-sm max-w-[200px]">왼쪽에서 문제 사진을 업로드하고<br>분석 버튼을 눌러주세요.</p>
            </div>
            """, unsafe_allow_html=True)

# ----------------------------------------------------------
# [4] 푸터 (저작권 표시 등)
# ----------------------------------------------------------
st.markdown("""
<footer class="py-8 text-center text-xs text-slate-400">
    <p>© 2025 MathAI Academy System. Designed for Teacher Support.</p>
</footer>
""", unsafe_allow_html=True)
