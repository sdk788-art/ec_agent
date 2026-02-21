import streamlit as st
import pandas as pd
import json
import anthropic

# ── 데이터 로드 (앱 시작 시 한 번만 실행) ──────────────────────────────────
@st.cache_data
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """4개 JSON 파일을 Pandas DataFrame으로 로드하여 반환."""
    customers = pd.read_json("data/customers.json")
    products  = pd.read_json("data/products.json")
    logs      = pd.read_json("data/logs.json")
    reviews   = pd.read_json("data/reviews.json")
    return customers, products, logs, reviews

customers, products, logs, reviews = load_data()

# ── Anthropic API 클라이언트 초기화 (실제 호출은 Step 2 이후 수행) ─────────
client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 자동 참조

# ── 세션 상태 초기화 ───────────────────────────────────────────────────────
if "current_customer" not in st.session_state:
    st.session_state.current_customer = None   # 로그인된 고객 정보 (dict)
if "search_results" not in st.session_state:
    st.session_state.search_results = None     # 마지막 검색 결과 DataFrame
if "selected_product_id" not in st.session_state:
    st.session_state.selected_product_id = None  # 상세 조회 중인 상품 ID

# ── 피부 타입 / 고민 한국어 매핑 테이블 ────────────────────────────────────
SKIN_TYPE_KO = {
    "dry":              "건성",
    "normal":           "중성",
    "oily":             "지성",
    "combination":      "복합성",
    "dehydrated_oily":  "수분부족 지성",
}

SKIN_CONCERN_KO = {
    "acne_trouble":         "여드름/트러블",
    "pores":                "모공",
    "wrinkles_aging":       "주름/노화",
    "pigmentation_blemish": "색소침착/잡티",
    "redness":              "홍조",
    "severe_dryness":       "극건조",
    "dullness":             "칙칙함",
}

# ── 사이드바: 고객 선택 및 로그인 ─────────────────────────────────────────
with st.sidebar:
    st.header("👤 고객 로그인")

    # 드롭다운 옵션 생성: "고객 ID — 성별, 나이" 형식
    def make_customer_label(row: pd.Series) -> str:
        gender_ko = {"female": "여성", "male": "남성", "other": "기타"}.get(row["gender"], row["gender"])
        return f"고객 {row['customer_id']:02d} — {gender_ko}, {row['age']}세"

    customer_options = {
        make_customer_label(row): row["customer_id"]
        for _, row in customers.iterrows()
    }
    label_list = ["선택하세요"] + list(customer_options.keys())

    selected_label = st.selectbox(
        "고객을 선택하세요",
        options=label_list,
        index=0,
    )

    login_btn = st.button("로그인", use_container_width=True)

    if login_btn:
        if selected_label == "선택하세요":
            st.warning("고객을 먼저 선택해주세요.")
        else:
            cid = customer_options[selected_label]
            matched = customers[customers["customer_id"] == cid]
            if not matched.empty:
                # DataFrame 행을 dict로 변환하여 세션에 저장
                st.session_state.current_customer = matched.iloc[0].to_dict()
                st.success(f"고객 {cid:02d}로 로그인되었습니다.")

    # 로그아웃 버튼 (로그인 상태일 때만 표시)
    if st.session_state.current_customer is not None:
        if st.button("로그아웃", use_container_width=True):
            st.session_state.current_customer = None
            st.session_state.search_results = None
            st.session_state.selected_product_id = None
            st.rerun()

# ── 메인 화면 ─────────────────────────────────────────────────────────────
st.title("✨ 뷰티 이커머스 AI 에이전트")
st.caption("H-A-S(Human-Agent-System) 아키텍처 기반 피부 맞춤 뷰티 쇼핑 도우미")

st.divider()

customer = st.session_state.current_customer

if customer is None:
    # 로그인 전 안내 메시지
    st.info("👈 왼쪽 사이드바에서 고객을 선택하고 로그인해주세요.")
else:
    # ── 로그인된 고객 피부 정보 표시 ──────────────────────────────────────
    st.subheader(f"안녕하세요, 고객 {int(customer['customer_id']):02d}님! 👋")

    col1, col2, col3 = st.columns(3)

    with col1:
        skin_type_ko = SKIN_TYPE_KO.get(customer["base_skin_type"], customer["base_skin_type"])
        st.metric(label="피부 타입", value=skin_type_ko)

    with col2:
        sensitive_ko = "예 🔴" if customer["is_sensitive"] else "아니오 🟢"
        st.metric(label="민감성 피부 여부", value=sensitive_ko)

    with col3:
        concerns = customer.get("skin_concerns", [])
        # JSON 로드 시 리스트가 문자열로 저장될 수 있으므로 안전하게 처리
        if isinstance(concerns, str):
            concerns = json.loads(concerns)
        concern_count = len(concerns) if concerns else 0
        st.metric(label="피부 고민 수", value=f"{concern_count}가지")

    # 피부 고민 태그 표시
    if concerns:
        concern_labels = [SKIN_CONCERN_KO.get(c, c) for c in concerns]
        st.write("**나의 피부 고민:**", " · ".join(f"`{label}`" for label in concern_labels))
    else:
        st.write("**나의 피부 고민:** 등록된 피부 고민이 없습니다.")

    st.divider()
    st.info("🔍 상품 검색 기능은 다음 단계에서 구현될 예정입니다.")
