import json

import streamlit as st
import streamlit.components.v1 as components

# 에이전트 함수 및 상수 임포트 (Anthropic API 호출 계층)
# agents.py 내부에서 load_dotenv()가 선행 실행되므로 별도 호출 불필요
from agents import (
    agent_parse_intent,
    agent_summarize_reviews,
    agent_recommend_cross_sell,
    SKIN_TYPE_KO,
    SKIN_CONCERN_KO,
    PRODUCT_TYPE_KO,
)

# 시스템 함수 및 데이터 임포트 (결정론적 데이터 처리 계층)
from logic import (
    customers,
    products,
    system_filter_products,
    system_get_same_skin_reviews,
    system_get_cross_sell_products,
)

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
if "current_page" not in st.session_state:
    st.session_state.current_page = 1          # 검색 결과 현재 페이지 번호
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "평점순"         # 검색 결과 정렬 기준
if "scroll_to_review" not in st.session_state:
    st.session_state.scroll_to_review = False  # 리뷰 섹션 자동 스크롤 트리거 플래그


# ── 정렬 옵션 상수 ──────────────────────────────────────────────────────────
# 표시 이름 → (DataFrame 컬럼명, 오름차순 여부) 매핑
_SORT_OPTIONS = ["평점순", "후기 많은순", "판매량 순", "낮은 가격순", "높은 가격순"]
_SORT_COLUMN_MAP: dict[str, tuple[str, bool]] = {
    "평점순":     ("avg_rating",   False),  # 내림차순
    "후기 많은순": ("review_count", False),  # 내림차순
    "판매량 순":  ("sales_volume", False),  # 내림차순
    "낮은 가격순": ("price",        True),   # 오름차순
    "높은 가격순": ("price",        False),  # 내림차순
}
_PAGE_SIZE = 10  # 페이지당 노출 상품 수


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
    """검색 결과 '상품 선택' 버튼 콜백: 선택 상품 ID를 세션에 저장하고 스크롤 플래그 설정."""
    st.session_state.selected_product_id = pid
    st.session_state.scroll_to_review = True  # 다음 렌더링 시 리뷰 섹션으로 자동 스크롤


def _cb_add_to_cart(pid: int) -> None:
    """'장바구니 담기/추가' 버튼 콜백: cart_added에 ID를 추가하고 풍선 효과 표시."""
    st.session_state.cart_added.add(pid)
    st.balloons()


def _cb_sort_changed() -> None:
    """정렬 기준 변경 시 페이지 번호를 1로 초기화."""
    st.session_state.current_page = 1


def _cb_prev_page() -> None:
    """이전 페이지 버튼 콜백: 첫 페이지가 아닌 경우 페이지 번호 1 감소."""
    if st.session_state.current_page > 1:
        st.session_state.current_page -= 1


def _cb_next_page(max_page: int) -> None:
    """다음 페이지 버튼 콜백: 마지막 페이지가 아닌 경우 페이지 번호 1 증가."""
    if st.session_state.current_page < max_page:
        st.session_state.current_page += 1


# ── 사이드바: 고객 선택 및 로그인 ─────────────────────────────────────────
with st.sidebar:
    st.header("👤 고객 로그인")

    # 드롭다운 옵션 생성: "고객 ID — 성별, 나이" 형식
    def make_customer_label(row) -> str:
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
            # 상품 선택 상태 및 페이지 번호 초기화
            st.session_state.selected_product_id = None
            st.session_state.current_page = 1

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

    # ── Step 2 / Micro-task 3 & 4: 검색 결과 표시 + 정렬 + 페이지네이션 ──────
    if st.session_state.search_results is not None:
        result_df = st.session_state.search_results

        st.divider()

        if result_df.empty:
            st.warning(
                "조건에 맞는 상품이 없습니다. "
                "검색어를 바꾸거나 더 넓은 조건으로 다시 검색해보세요."
            )
        else:
            total_count = len(result_df)
            st.write(f"**총 {total_count}개의 상품**을 찾았습니다.")

            # 정렬 기준 선택 UI
            # key="sort_by"로 세션 상태와 직접 연동; on_change로 페이지 번호 초기화
            st.selectbox(
                "정렬 기준",
                options=_SORT_OPTIONS,
                key="sort_by",
                on_change=_cb_sort_changed,
            )

            # 선택된 정렬 기준으로 DataFrame 정렬
            sort_col, sort_asc = _SORT_COLUMN_MAP[st.session_state.sort_by]
            sorted_df = result_df.sort_values(sort_col, ascending=sort_asc).reset_index(drop=True)

            # 페이지네이션 계산 (올림 나눗셈으로 총 페이지 수 산출)
            total_pages = max(1, -(-total_count // _PAGE_SIZE))
            current_page = st.session_state.current_page

            # 안전장치: 정렬 변경 또는 결과 변동으로 페이지가 범위를 벗어날 경우 조정
            if current_page > total_pages:
                st.session_state.current_page = total_pages
                current_page = total_pages

            start_idx = (current_page - 1) * _PAGE_SIZE
            end_idx   = start_idx + _PAGE_SIZE
            page_df   = sorted_df.iloc[start_idx:end_idx]

            # 현재 페이지 상품 카드 렌더링
            for _, row in page_df.iterrows():
                with st.container(border=True):
                    # 상품 정보 컬럼 (왼쪽) + 선택 버튼 (오른쪽)
                    info_col, btn_col = st.columns([4, 1])

                    with info_col:
                        product_type_ko = PRODUCT_TYPE_KO.get(
                            row["product_type"], row["product_type"]
                        )
                        # 평점 표시: 리뷰가 있는 경우 평점 + 건수, 없는 경우 "리뷰 없음"
                        avg_rating   = float(row.get("avg_rating",   0.0))
                        review_count = int(row.get("review_count", 0))
                        if review_count > 0:
                            rating_str = f"⭐ {avg_rating:.1f} ({review_count}건)"
                        else:
                            rating_str = "⭐ 리뷰 없음"

                        # 상품명, 카테고리 태그, 평점 한 줄 표시
                        st.markdown(
                            f"**{row['product_name']}**&nbsp;&nbsp;"
                            f"`{product_type_ko}`&nbsp;&nbsp;"
                            f"{rating_str}"
                        )
                        # 브랜드, 가격, 재고
                        st.caption(
                            f"브랜드: {row['brand']} &nbsp;|&nbsp; "
                            f"가격: {int(row['price']):,}원 &nbsp;|&nbsp; "
                            f"재고: {int(row['stock'])}개"
                        )
                        # 한 줄 대표 리뷰 (description)
                        if row.get("description"):
                            st.info(f"💬 {row['description']}")

                    # Micro-task 4: 상품 선택 버튼 (on_click 콜백 → 단일 클릭 동작)
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

            # 페이지 네비게이션 바 (이전 / 페이지 표시 / 다음)
            nav_left, nav_center, nav_right = st.columns([1, 2, 1])
            with nav_left:
                st.button(
                    "⬅ 이전 페이지",
                    on_click=_cb_prev_page,
                    disabled=(current_page <= 1),
                    use_container_width=True,
                    key="btn_prev_page",
                )
            with nav_center:
                st.markdown(
                    f"<div style='text-align:center; padding-top:8px'>"
                    f"<b>{current_page} / {total_pages} 페이지</b></div>",
                    unsafe_allow_html=True,
                )
            with nav_right:
                st.button(
                    "다음 페이지 ➡",
                    on_click=_cb_next_page,
                    args=(total_pages,),
                    disabled=(current_page >= total_pages),
                    use_container_width=True,
                    key="btn_next_page",
                )

    # ── Step 3: 상품 상세 / 리뷰 요약 / 시너지 상품 추천 ──────────────────
    # 자동 스크롤 앵커: 상품 선택 시 이 위치로 부드럽게 스크롤
    st.markdown('<div id="review-anchor"></div>', unsafe_allow_html=True)

    if st.session_state.selected_product_id is not None:
        # 상품 선택 직후 첫 렌더링에서만 리뷰 섹션으로 자동 스크롤
        # scroll_to_review 플래그 소비 후 즉시 False로 초기화 → 이후 재렌더링에서 반복 스크롤 방지
        if st.session_state.scroll_to_review:
            st.session_state.scroll_to_review = False
            components.html(
                """
                <script>
                    // Streamlit은 iframe 내부에서 실행 → window.parent로 부모 문서에 접근
                    // setInterval 폴링: 앵커가 DOM에 등장할 때까지 최대 10회(100ms 간격) 재시도
                    var attempts = 0;
                    var maxAttempts = 10;
                    console.log("[AutoScroll] 앵커 탐색 시작...");
                    var timer = setInterval(function () {
                        attempts++;
                        var el = window.parent.document.getElementById("review-anchor");
                        if (el) {
                            clearInterval(timer);
                            el.scrollIntoView({ behavior: "smooth", block: "start" });
                            console.log("[AutoScroll] 스크롤 실행 완료 (시도 횟수: " + attempts + ")");
                        } else if (attempts >= maxAttempts) {
                            clearInterval(timer);
                            console.log("[AutoScroll] 앵커를 찾지 못했습니다 (" + maxAttempts + "회 시도 후 중단)");
                        } else {
                            console.log("[AutoScroll] 앵커 탐색 중... (" + attempts + "/" + maxAttempts + ")");
                        }
                    }, 100);
                </script>
                """,
                height=0,  # 화면에 표시되지 않는 0px 높이 iframe
            )

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
