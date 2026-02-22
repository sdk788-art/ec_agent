import json

import anthropic
import pandas as pd
from dotenv import load_dotenv

# .env 파일에서 ANTHROPIC_API_KEY 환경변수 로드 (agents 모듈 임포트 시 선행 실행)
load_dotenv()

# ── Anthropic API 클라이언트 초기화 (ANTHROPIC_API_KEY 환경변수 자동 참조) ──
client = anthropic.Anthropic()

# ── 피부 타입 / 고민 / 상품 종류 한국어 매핑 테이블 ─────────────────────────
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
