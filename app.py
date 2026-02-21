import streamlit as st
import pandas as pd
import json
import anthropic
from dotenv import load_dotenv

# .env 파일에서 ANTHROPIC_API_KEY 등 환경변수 로드 (app.py와 동일 폴더 기준)
load_dotenv()

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
if "last_search_query" not in st.session_state:
    st.session_state.last_search_query = ""    # 마지막 검색어 (LLM 캐시 무효화 기준)
if "cart_added" not in st.session_state:
    st.session_state.cart_added = set()        # 장바구니에 담긴 상품 ID 집합

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


# ── Step 3 / Micro-task 5: System — 동일 피부 타입 리뷰 필터링 및 지표 계산 ──
def system_get_same_skin_reviews(product_id: int, skin_type: str) -> tuple[pd.DataFrame, dict]:
    """S → A: 선택 상품의 동일 피부 타입 고객 리뷰를 필터링하고 정량 지표를 계산.

    H-A-S 원칙: LLM에 전달하기 전 Pandas로 교차 검증 및 필터링 수행.
    반환값 tuple:
      - filtered_df : 조건에 맞는 리뷰 DataFrame
      - metrics     : 정량 지표 dict (total, avg_rate, satisfaction_pct)
    """
    # 동일 피부 타입 고객 ID 목록 추출
    same_type_ids = customers[customers["base_skin_type"] == skin_type]["customer_id"]

    # 선택 상품 + 동일 피부 타입 고객 리뷰만 필터링
    filtered = reviews[
        (reviews["product_id"] == product_id) &
        (reviews["customer_id"].isin(same_type_ids))
    ].copy()

    total = len(filtered)

    if total > 0:
        avg_rate = round(filtered["rate"].mean(), 2)
        high_satisfaction = int((filtered["rate"] >= 4.0).sum())
        satisfaction_pct = round(high_satisfaction / total * 100, 1)
    else:
        avg_rate = 0.0
        satisfaction_pct = 0.0

    metrics = {
        "total_reviews": total,
        "avg_rate": avg_rate,
        "satisfaction_pct": satisfaction_pct,
    }

    return filtered, metrics


# ── Step 3 / Micro-task 6: Agent — 필터링된 리뷰 텍스트를 LLM이 요약 ─────────
def agent_summarize_reviews(
    filtered_reviews_df: pd.DataFrame,
    skin_type: str,
    metrics: dict,
) -> str:
    """S → A: 사전 필터링된 리뷰 텍스트와 정량 지표만 LLM에 전달하여 요약 생성.

    H-A-S 원칙: System이 먼저 필터링한 결과물만 Agent에 전달 (전체 DB 비전달).
    프롬프트 지시: 반드시 한국어로 출력.
    """
    review_texts = filtered_reviews_df["review"].dropna().tolist()

    if not review_texts:
        return None  # 텍스트 리뷰 없음 → 호출 불필요

    skin_type_ko = SKIN_TYPE_KO.get(skin_type, skin_type)
    reviews_joined = "\n".join(f"- {text}" for text in review_texts)

    prompt = (
        f"다음은 {skin_type_ko} 피부 고객들이 남긴 리뷰입니다.\n"
        f"[정량 지표] 총 {metrics['total_reviews']}건 · 평균 평점 {metrics['avg_rate']}점 · "
        f"만족도(4점 이상) {metrics['satisfaction_pct']}%\n\n"
        f"[리뷰 목록]\n{reviews_joined}\n\n"
        "이 고객들의 만족 및 불만족 포인트를 한국어로 자연스럽게 2~3문장으로 요약해 주세요."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ── Step 3 / Micro-task 8: System — 함께 구매 빈도 기반 시너지 상품 추출 ─────
def system_get_cross_sell_products(selected_id: int, top_n: int = 2) -> pd.DataFrame:
    """S → A: 선택 상품과 가장 자주 함께 구매된 상위 N개 상품을 결정론적으로 추출.

    H-A-S 원칙: LLM 개입 없이 순수 Pandas 집계 연산만 사용.
    """
    purchase_logs = logs[logs["action_type"] == "purchase"]

    # 선택 상품을 구매한 고객 ID
    buyers = purchase_logs[purchase_logs["product_id"] == selected_id]["customer_id"]

    if buyers.empty:
        return pd.DataFrame()

    # 해당 고객들이 구매한 다른 상품 (선택 상품 제외)
    co_purchases = purchase_logs[
        (purchase_logs["customer_id"].isin(buyers)) &
        (purchase_logs["product_id"] != selected_id)
    ]

    if co_purchases.empty:
        return pd.DataFrame()

    # 함께 구매 빈도 상위 top_n 상품 ID 추출
    top_ids = (
        co_purchases.groupby("product_id").size()
        .nlargest(top_n)
        .index.tolist()
    )

    return products[products["product_id"].isin(top_ids)].copy().reset_index(drop=True)


# ── Step 3 / Micro-task 9: Agent — 시너지 상품 크로스셀링 메시지 생성 ──────────
def agent_recommend_cross_sell(
    selected_product: pd.Series,
    cross_sell_df: pd.DataFrame,
    customer: dict,
) -> str:
    """S → A: 시너지 상품 정보와 고객 피부 고민을 LLM에 전달하여 크로스셀링 메시지 생성.

    H-A-S 원칙: System이 추출한 상품 정보만 Agent에 전달 (전체 DB 비전달).
    프롬프트 지시: 반드시 한국어 2~3문장으로 출력.
    """
    # 고객 피부 고민 한국어 변환
    concerns = customer.get("skin_concerns", [])
    if isinstance(concerns, str):
        concerns = json.loads(concerns)
    concern_labels = [SKIN_CONCERN_KO.get(c, c) for c in concerns]
    concern_str = ", ".join(concern_labels) if concern_labels else "없음"

    # 추천 상품 목록 (이름 + 카테고리)
    cross_items = [
        f"'{row['product_name']}'({PRODUCT_TYPE_KO.get(row['product_type'], row['product_type'])})"
        for _, row in cross_sell_df.iterrows()
    ]
    cross_str = ", ".join(cross_items)

    prompt = (
        f"현재 고객의 피부 고민은 {concern_str}입니다.\n"
        f"이 고객이 현재 보고 있는 상품 '{selected_product['product_name']}'과 "
        f"{cross_str}을(를) 함께 사용했을 때의 시너지 효과를 강조하는 "
        "매력적인 크로스셀링 메시지를 2~3문장의 한국어로 작성해 주세요."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ── LLM 캐시 관리 유틸리티 ──────────────────────────────────────────────────
def _clear_llm_caches() -> None:
    """새로운 검색어 입력 시 세션에 저장된 LLM 결과 캐시를 전부 삭제.

    삭제 대상:
      - review_summary_{product_id}_{skin_type}  : 리뷰 요약 캐시
      - cross_msg_{product_id}_{customer_id}     : 크로스셀링 메시지 캐시
    삭제하지 않는 대상:
      - current_customer, search_results, selected_product_id 등 핵심 상태
    """
    keys_to_delete = [
        k for k in list(st.session_state.keys())
        if k.startswith("review_summary_") or k.startswith("cross_msg_")
    ]
    for k in keys_to_delete:
        del st.session_state[k]


# ── UI 버튼 콜백 함수 ──────────────────────────────────────────────────────
# on_click 콜백은 스크립트 재실행(rerun) 이전에 실행되므로,
# 상태 변경이 즉시 반영되어 한 번의 클릭만으로 UI가 업데이트된다.

def _cb_select_product(pid: int) -> None:
    """검색 결과 '상품 선택' 버튼 콜백: 선택 상품 ID를 세션에 저장."""
    st.session_state.selected_product_id = pid


def _cb_add_to_cart(pid: int) -> None:
    """'장바구니 담기/추가' 버튼 콜백: cart_added에 ID를 추가하고 풍선 효과 표시."""
    st.session_state.cart_added.add(pid)
    st.balloons()


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
                # 고객 변경 시 이전 검색 결과 및 LLM 캐시 전부 초기화
                st.session_state.search_results = None
                st.session_state.selected_product_id = None
                st.session_state.parsed_params = None
                st.session_state.last_search_query = ""
                st.session_state.cart_added = set()
                _clear_llm_caches()
                st.success(f"고객 {cid:02d}로 로그인되었습니다.")

    # 로그아웃 버튼 (로그인 상태일 때만 표시)
    if st.session_state.current_customer is not None:
        if st.button("로그아웃", use_container_width=True):
            st.session_state.current_customer = None
            st.session_state.search_results = None
            st.session_state.selected_product_id = None
            st.session_state.parsed_params = None
            st.session_state.last_search_query = ""
            st.session_state.cart_added = set()
            _clear_llm_caches()
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
            new_query = search_query.strip()

            # 요구사항 3: 새로운 검색어일 때만 LLM 캐시 초기화
            # → 동일 검색어 재검색 시 기존 캐시 재사용, 불필요한 API 호출 방지
            if new_query != st.session_state.last_search_query:
                _clear_llm_caches()
                st.session_state.last_search_query = new_query
                st.session_state.cart_added = set()  # 장바구니 상태도 초기화

            # Micro-task 2: Agent — 자연어 → JSON 파라미터 파싱
            with st.spinner("AI가 검색어를 분석 중입니다..."):
                try:
                    parsed = agent_parse_intent(new_query)
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
                    # on_click 콜백으로 교체 → 클릭 즉시 상태 반영 (단일 클릭 동작)
                    with btn_col:
                        is_selected = (
                            st.session_state.selected_product_id == row["product_id"]
                        )
                        btn_label = "✅ 선택됨" if is_selected else "상품 선택"
                        st.button(
                            btn_label,
                            key=f"select_{row['product_id']}",
                            use_container_width=True,
                            type="primary" if is_selected else "secondary",
                            on_click=_cb_select_product,
                            args=(int(row["product_id"]),),
                        )

    # ── Step 3: 상품 상세 / 리뷰 요약 / 시너지 상품 추천 ──────────────────
    if st.session_state.selected_product_id is not None:
        selected_id = st.session_state.selected_product_id
        selected_row = products[products["product_id"] == selected_id]

        if not selected_row.empty:
            p = selected_row.iloc[0]
            skin_type = customer["base_skin_type"]
            skin_type_ko = SKIN_TYPE_KO.get(skin_type, skin_type)

            st.divider()

            # ── Micro-task 7 (상단): 상품 상세 정보 ────────────────────────
            st.subheader(f"📦 {p['product_name']}")

            d1, d2, d3, d4 = st.columns(4)
            with d1:
                st.metric("카테고리", PRODUCT_TYPE_KO.get(p["product_type"], p["product_type"]))
            with d2:
                st.metric("브랜드", p["brand"])
            with d3:
                st.metric("가격", f"{int(p['price']):,}원")
            with d4:
                st.metric("재고", f"{int(p['stock'])}개")

            if p.get("description"):
                st.info(f"💬 {p['description']}")

            st.divider()

            # ── Micro-task 5: System — 동일 피부 타입 리뷰 필터링 및 지표 계산 ──
            filtered_reviews_df, metrics = system_get_same_skin_reviews(selected_id, skin_type)

            st.subheader(f"🔍 {skin_type_ko} 피부 고객 리뷰 분석")

            m1, m2, m3 = st.columns(3)
            with m1:
                st.metric("동일 피부 타입 리뷰", f"{metrics['total_reviews']}건")
            with m2:
                avg_display = f"⭐ {metrics['avg_rate']:.1f} / 5.0" if metrics["total_reviews"] > 0 else "N/A"
                st.metric("평균 평점", avg_display)
            with m3:
                sat_display = f"{metrics['satisfaction_pct']}%" if metrics["total_reviews"] > 0 else "N/A"
                st.metric("만족도 (4점↑)", sat_display)

            # ── Micro-task 6: Agent — 리뷰 요약 (세션 캐시로 중복 API 호출 방지) ──
            # 캐시 키에 skin_type 포함 → 다른 피부 타입 고객 로그인 시 재계산
            review_cache_key = f"review_summary_{selected_id}_{skin_type}"

            if review_cache_key not in st.session_state:
                if metrics["total_reviews"] > 0:
                    with st.spinner("AI가 리뷰를 분석하고 요약 중입니다..."):
                        st.session_state[review_cache_key] = agent_summarize_reviews(
                            filtered_reviews_df, skin_type, metrics
                        )
                else:
                    # 리뷰 없음 → API 호출 생략
                    st.session_state[review_cache_key] = None

            # ── Micro-task 7 (중단): AI 리뷰 요약 출력 ────────────────────────
            st.subheader("🤖 AI 리뷰 요약")
            summary = st.session_state.get(review_cache_key)
            if summary:
                st.success(summary)
            else:
                st.info(f"{skin_type_ko} 피부 타입 고객이 남긴 리뷰가 아직 없습니다.")

            # ── Micro-task 7 (하단): 장바구니 담기 버튼 ───────────────────────
            # on_click 콜백 패턴: 클릭 즉시 cart_added에 추가 → 단일 클릭으로 UI 업데이트
            main_pid = int(selected_id)
            if main_pid in st.session_state.cart_added:
                # 이미 담긴 상태: 비활성화 버튼으로 완료 피드백 표시
                st.button(
                    "✅ 장바구니에 담겼습니다",
                    type="primary",
                    key=f"cart_{main_pid}",
                    disabled=True,
                )
            else:
                st.button(
                    "🛒 장바구니 담기",
                    type="primary",
                    key=f"cart_{main_pid}",
                    on_click=_cb_add_to_cart,
                    args=(main_pid,),
                )

            st.divider()

            # ── Micro-task 8: System — 함께 구매 빈도 기반 시너지 상품 추출 ─────
            cross_df = system_get_cross_sell_products(selected_id, top_n=2)

            # ── Micro-task 9: Agent — 크로스셀링 메시지 생성 및 UI 출력 ─────────
            if not cross_df.empty:
                # 캐시 키에 customer_id 포함 → 피부 고민이 다른 고객에게 재계산
                customer_id = int(customer["customer_id"])
                cross_msg_key = f"cross_msg_{selected_id}_{customer_id}"

                if cross_msg_key not in st.session_state:
                    with st.spinner("AI가 맞춤 시너지 추천 메시지를 작성 중입니다..."):
                        st.session_state[cross_msg_key] = agent_recommend_cross_sell(
                            p, cross_df, customer
                        )

                st.subheader("✨ 함께 쓰면 더 좋은 시너지 상품")

                # AI 크로스셀링 메시지 출력
                cross_msg = st.session_state.get(cross_msg_key)
                if cross_msg:
                    st.info(f"💡 {cross_msg}")

                # 추천 상품 카드 표시
                for _, cs_row in cross_df.iterrows():
                    with st.container(border=True):
                        cs_type_ko = PRODUCT_TYPE_KO.get(cs_row["product_type"], cs_row["product_type"])
                        cs_info_col, cs_btn_col = st.columns([4, 1])
                        with cs_info_col:
                            st.markdown(
                                f"**{cs_row['product_name']}**&nbsp;&nbsp;`{cs_type_ko}`"
                            )
                            st.caption(
                                f"브랜드: {cs_row['brand']} &nbsp;|&nbsp; "
                                f"가격: {int(cs_row['price']):,}원 &nbsp;|&nbsp; "
                                f"재고: {int(cs_row['stock'])}개"
                            )
                            if cs_row.get("description"):
                                st.write(f"💬 {cs_row['description']}")
                        with cs_btn_col:
                            cs_id = int(cs_row["product_id"])
                            already_in_cart = cs_id in st.session_state.cart_added
                            if already_in_cart:
                                # 이미 담긴 상태: 비활성화 버튼으로 완료 피드백 표시
                                st.button(
                                    "✅ 담겼습니다",
                                    key=f"cart_cross_{cs_id}",
                                    use_container_width=True,
                                    disabled=True,
                                )
                            else:
                                # on_click 콜백 패턴: 단일 클릭으로 즉시 상태 반영
                                # selected_product_id 불변 → LLM 캐시 그대로 유지
                                st.button(
                                    "🛒 장바구니 추가",
                                    key=f"cart_cross_{cs_id}",
                                    use_container_width=True,
                                    on_click=_cb_add_to_cart,
                                    args=(cs_id,),
                                )
            else:
                st.info("이 상품과 함께 구매된 데이터가 충분하지 않아 시너지 추천을 제공할 수 없습니다.")
