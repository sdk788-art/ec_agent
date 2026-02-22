import json

import pandas as pd
import streamlit as st


# ── 데이터 로드 (앱 시작 시 한 번만 실행) ──────────────────────────────────
@st.cache_data
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """4개 JSON 파일을 Pandas DataFrame으로 로드하여 반환."""
    customers = pd.read_json("data/customers.json")
    products  = pd.read_json("data/products.json")
    logs      = pd.read_json("data/logs.json")
    reviews   = pd.read_json("data/reviews.json")
    return customers, products, logs, reviews


# 모듈 임포트 시 데이터 로드 (Streamlit 캐시 적용으로 중복 I/O 방지)
customers, products, logs, reviews = load_data()


# ── 배열 컬럼 변환 유틸리티 ──────────────────────────────────────────────────
def _to_list(value) -> list:
    """DataFrame 배열 컬럼 값을 안전하게 Python list로 변환."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return []


# ── 검색 결과 상품 지표 집계: 평점 평균, 리뷰 수, 판매량 ───────────────────────
def system_aggregate_product_stats(products_df: pd.DataFrame) -> pd.DataFrame:
    """검색된 상품 DataFrame에 평점 평균(avg_rating), 리뷰 수(review_count),
    판매량(sales_volume) 지표를 병합하여 반환.

    H-A-S 원칙: LLM 개입 없이 순수 Pandas 집계 연산만 사용.
    리뷰나 판매량이 없는 상품은 결측치를 0으로 처리.
    """
    if products_df.empty:
        # 빈 DataFrame에도 정렬용 컬럼 추가
        result = products_df.copy()
        result["avg_rating"]   = 0.0
        result["review_count"] = 0
        result["sales_volume"] = 0
        return result

    product_ids = products_df["product_id"].tolist()

    # 평점 평균 및 리뷰 수 계산 (reviews 테이블 집계)
    product_reviews = reviews[reviews["product_id"].isin(product_ids)]
    if not product_reviews.empty:
        rating_stats = (
            product_reviews.groupby("product_id")
            .agg(avg_rating=("rate", "mean"), review_count=("rate", "count"))
            .reset_index()
        )
        rating_stats["avg_rating"] = rating_stats["avg_rating"].round(1)
    else:
        rating_stats = pd.DataFrame(columns=["product_id", "avg_rating", "review_count"])

    # 판매량 계산 (logs 테이블에서 purchase 행만 집계)
    purchase_logs = logs[logs["action_type"] == "purchase"]
    product_purchases = purchase_logs[purchase_logs["product_id"].isin(product_ids)]
    if not product_purchases.empty:
        sales_stats = (
            product_purchases.groupby("product_id")
            .size()
            .reset_index(name="sales_volume")
        )
    else:
        sales_stats = pd.DataFrame(columns=["product_id", "sales_volume"])

    # 세 지표를 상품 DataFrame에 left-join 병합
    result = products_df.copy()
    result = result.merge(rating_stats, on="product_id", how="left")
    result = result.merge(sales_stats,  on="product_id", how="left")

    # 결측치 처리: 리뷰/판매 이력 없는 상품은 0으로 대체
    result["avg_rating"]   = result["avg_rating"].fillna(0.0)
    result["review_count"] = result["review_count"].fillna(0).astype(int)
    result["sales_volume"] = result["sales_volume"].fillna(0).astype(int)

    return result


# ── Step 2 / Micro-task 3: System — 결정론적 Pandas 필터링 ─────────────────
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

    # 전체 필터링 결과에 평점·리뷰 수·판매량 지표를 병합하여 반환
    # (페이지네이션은 app.py에서 처리하므로 head 제한 없음)
    return system_aggregate_product_stats(result.reset_index(drop=True))


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

    # Agent에게 전달할 리뷰 샘플링: 최신순 정렬 후 최대 5건만 추출
    MAX_SAMPLE = 5
    MAX_REVIEW_LEN = 300
    sampled = filtered.sort_values("created_at", ascending=False).head(MAX_SAMPLE).copy()

    # 텍스트 방어 로직: 300자 초과 리뷰는 잘라내고 "..." 추가
    def _truncate_review(text) -> str:
        if pd.isna(text):
            return text
        text_str = str(text)
        if len(text_str) > MAX_REVIEW_LEN:
            return text_str[:MAX_REVIEW_LEN] + "..."
        return text_str

    sampled["review"] = sampled["review"].apply(_truncate_review)

    return sampled, metrics


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
