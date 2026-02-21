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

# ── Anthropic API 클라이언트 초기화 ─────────────────────────────────────────
client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 자동 참조

# ── 세션 상태 초기화 ───────────────────────────────────────────────────────
if "current_customer" not in st.session_state:
    st.session_state.current_customer = None   # 로그인된 고객 정보 (dict)
if "search_results" not in st.session_state:
    st.session_state.search_results = None     # 마지막 검색 결과 DataFrame
if "selected_product_id" not in st.session_state:
    st.session_state.selected_product_id = None  # 상세 조회 중인 상품 ID
if "parsed_params" not in st.session_state:
    st.session_state.parsed_params = None      # Agent가 파싱한 검색 파라미터 dict

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

PRODUCT_TYPE_KO = {
    "cleansing_foam":       "클렌징폼",
    "cleansing_oil_water":  "클렌징 오일/워터",
    "exfoliator_peeling":   "각질제거/필링",
    "toner":                "토너",
    "toner_pad":            "토너패드",
    "essence":              "에센스",
    "serum":                "세럼",
    "ampoule":              "앰플",
    "lotion_emulsion":      "로션/에멀전",
    "moisture_cream":       "수분크림",
    "eye_cream":            "아이크림",
    "face_oil":             "페이스오일",
    "sheet_mask":           "시트마스크",
    "wash_off_mask":        "워시오프마스크",
    "sun_care":             "선케어",
    "lip_care":             "립케어",
}

# ── Step 2 / Micro-task 2: Agent — 자연어 검색어를 JSON 파라미터로 파싱 ─────
def agent_parse_intent(query: str) -> dict:
    """H → A: 자연어 검색어에서 상품 종류와 피부 고민을 추출하여 JSON으로 반환.

    LLM은 오직 검색어를 파라미터 JSON으로 변환하는 작업만 수행한다.
    전체 DB는 절대 LLM에 전달하지 않는다 (H-A-S 원칙).
    """
    system_prompt = (
        "당신은 뷰티 이커머스 검색 파라미터 추출 전문가입니다.\n"
        "사용자의 검색어에서 상품 종류(product_type)와 기대 효과/피부 고민(concerns)을 추출하여 "
        "아래 형식의 JSON만 반환하세요. 다른 텍스트는 절대 출력하지 마세요.\n\n"
        "반환 형식:\n"
        '{"product_type": "상품 종류 또는 null", "concerns": ["고민1", "고민2"]}\n\n'
        "product_type 허용값(해당 없으면 null):\n"
        "cleansing_foam, cleansing_oil_water, exfoliator_peeling, toner, toner_pad, "
        "essence, serum, ampoule, lotion_emulsion, moisture_cream, eye_cream, face_oil, "
        "sheet_mask, wash_off_mask, sun_care, lip_care\n\n"
        "concerns 허용값(해당 없으면 빈 배열 []):\n"
        "acne_trouble, pores, wrinkles_aging, pigmentation_blemish, redness, "
        "severe_dryness, dullness"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system=system_prompt,
        messages=[{"role": "user", "content": query}],
    )
    raw = response.content[0].text.strip()

    # LLM이 코드 블록(```)으로 감싸서 반환하는 경우 안전하게 제거
    if "```" in raw:
        parts = raw.split("```")
        # 코드 블록 내부 추출 (index 1)
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:].strip()

    return json.loads(raw)


# ── Step 2 / Micro-task 3: System — 결정론적 Pandas 필터링 ─────────────────
def _to_list(value) -> list:
    """DataFrame 배열 컬럼 값을 안전하게 Python list로 변환."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return []


def system_filter_products(params: dict, customer: dict) -> pd.DataFrame:
    """A → S: Agent 파라미터 + 고객 피부 정보로 상품을 결정론적 필터링.

    H-A-S 원칙: LLM 개입 없이 순수 Pandas 연산만 사용.
    필터 순서:
      1) product_type  — LLM이 추출한 상품 종류 (exact match)
      2) target_skin_types — 고객 피부 타입 포함 여부 (set-intersection)
      3) target_concerns   — LLM 고민 ∪ 고객 고민 중 하나라도 매칭 (set-intersection)
    """
    result = products.copy()

    # 1. 상품 종류 필터 (LLM 파라미터)
    product_type = params.get("product_type")
    if product_type and product_type != "null":
        result = result[result["product_type"] == product_type]

    # 2. 피부 타입 필터 — 고객의 base_skin_type이 target_skin_types에 포함된 상품
    skin_type = customer.get("base_skin_type")
    if skin_type:
        result = result[
            result["target_skin_types"].apply(lambda x: skin_type in _to_list(x))
        ]

    # 3. 피부 고민 필터 — LLM 추출 고민과 고객 등록 고민의 합집합으로 교집합 검사
    llm_concerns = set(params.get("concerns") or [])
    raw_customer_concerns = customer.get("skin_concerns", [])
    customer_concerns = set(_to_list(raw_customer_concerns))
    all_concerns = llm_concerns | customer_concerns

    if all_concerns:
        result = result[
            result["target_concerns"].apply(
                lambda x: bool(all_concerns & set(_to_list(x)))
            )
        ]

    return result.reset_index(drop=True)


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
                # 고객 변경 시 이전 검색 결과 초기화
                st.session_state.search_results = None
                st.session_state.selected_product_id = None
                st.session_state.parsed_params = None
                st.success(f"고객 {cid:02d}로 로그인되었습니다.")

    # 로그아웃 버튼 (로그인 상태일 때만 표시)
    if st.session_state.current_customer is not None:
        if st.button("로그아웃", use_container_width=True):
            st.session_state.current_customer = None
            st.session_state.search_results = None
            st.session_state.selected_product_id = None
            st.session_state.parsed_params = None
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

    # ── Step 2 / Micro-task 1: Human — 자연어 검색 입력 UI ────────────────
    st.subheader("🔍 상품 검색")
    st.caption("자연어로 원하는 상품을 검색해보세요. AI가 내 피부에 맞는 상품을 찾아드립니다.")

    search_query = st.text_input(
        label="검색어를 입력하세요",
        placeholder="예) 민감성 피부 진정 마스크팩, 여드름 피부 클렌징폼, 건성 피부 수분크림",
        max_chars=200,
        key="search_query_input",
    )

    search_btn = st.button("검색", type="primary", use_container_width=False)

    # ── 검색 버튼 클릭 처리 ────────────────────────────────────────────────
    if search_btn:
        if not search_query.strip():
            st.warning("검색어를 입력해주세요.")
        else:
            # Micro-task 2: Agent — 자연어 → JSON 파라미터 파싱
            with st.spinner("AI가 검색어를 분석 중입니다..."):
                try:
                    parsed = agent_parse_intent(search_query.strip())
                    st.session_state.parsed_params = parsed
                except (json.JSONDecodeError, Exception) as e:
                    st.error(f"검색어 분석 중 오류가 발생했습니다: {e}")
                    st.session_state.parsed_params = None
                    st.stop()

            # Micro-task 3: System — 결정론적 Pandas 필터링
            filtered = system_filter_products(st.session_state.parsed_params, customer)
            st.session_state.search_results = filtered
            # 상품 선택 상태 초기화
            st.session_state.selected_product_id = None

    # ── 파싱된 파라미터 표시 (검색 투명성 확보) ────────────────────────────
    if st.session_state.parsed_params is not None:
        params = st.session_state.parsed_params
        with st.expander("🤖 AI 분석 결과 보기", expanded=False):
            pt = params.get("product_type")
            pt_ko = PRODUCT_TYPE_KO.get(pt, pt) if pt and pt != "null" else "전체 카테고리"
            concern_ko_list = [SKIN_CONCERN_KO.get(c, c) for c in (params.get("concerns") or [])]

            col_p, col_c = st.columns(2)
            with col_p:
                st.write(f"**추출된 상품 종류:** `{pt_ko}`")
            with col_c:
                if concern_ko_list:
                    st.write("**추출된 피부 고민:**", ", ".join(f"`{c}`" for c in concern_ko_list))
                else:
                    st.write("**추출된 피부 고민:** 없음")

    # ── Step 2 / Micro-task 3 & 4: 검색 결과 표시 + 상품 선택 버튼 ─────────
    if st.session_state.search_results is not None:
        result_df = st.session_state.search_results

        st.divider()

        if result_df.empty:
            st.warning(
                "조건에 맞는 상품이 없습니다. "
                "검색어를 바꾸거나 더 넓은 조건으로 다시 검색해보세요."
            )
        else:
            st.write(f"**총 {len(result_df)}개의 상품**을 찾았습니다.")

            # 각 상품을 카드 형태로 표시
            for _, row in result_df.iterrows():
                with st.container(border=True):
                    # 상품 정보 컬럼 (왼쪽) + 선택 버튼 (오른쪽)
                    info_col, btn_col = st.columns([4, 1])

                    with info_col:
                        product_type_ko = PRODUCT_TYPE_KO.get(
                            row["product_type"], row["product_type"]
                        )
                        # 상품명 및 카테고리 태그
                        st.markdown(
                            f"**{row['product_name']}**&nbsp;&nbsp;"
                            f"`{product_type_ko}`"
                        )
                        # 브랜드 및 가격
                        st.caption(
                            f"브랜드: {row['brand']} &nbsp;|&nbsp; "
                            f"가격: {int(row['price']):,}원 &nbsp;|&nbsp; "
                            f"재고: {int(row['stock'])}개"
                        )
                        # 한 줄 대표 리뷰 (description)
                        if row.get("description"):
                            st.info(f"💬 {row['description']}")

                    # Micro-task 4: 상품 선택 버튼
                    with btn_col:
                        is_selected = (
                            st.session_state.selected_product_id == row["product_id"]
                        )
                        btn_label = "✅ 선택됨" if is_selected else "상품 선택"
                        if st.button(
                            btn_label,
                            key=f"select_{row['product_id']}",
                            use_container_width=True,
                            type="primary" if is_selected else "secondary",
                        ):
                            # 선택된 상품 ID를 세션 상태에 저장
                            st.session_state.selected_product_id = int(row["product_id"])
                            st.rerun()

    # ── 선택된 상품 정보 요약 표시 ────────────────────────────────────────
    if st.session_state.selected_product_id is not None:
        selected_id = st.session_state.selected_product_id
        selected_row = products[products["product_id"] == selected_id]

        if not selected_row.empty:
            p = selected_row.iloc[0]
            st.divider()
            st.subheader(f"📦 선택한 상품: {p['product_name']}")
            st.success(
                f"상품 ID **{selected_id}**번이 선택되었습니다. "
                "다음 단계에서 피부 타입별 리뷰 요약을 제공합니다."
            )
