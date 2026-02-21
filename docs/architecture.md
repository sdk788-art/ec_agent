# Architecture Memo: Beauty E-Commerce Agent

본 아키텍처는 채널코퍼레이션이 지향하는 **환각(Hallucination) 없는 신뢰할 수 있는 AI**를 구현하기 위해 설계되었습니다. 단순 RAG(검색 증강 생성)에 의존하지 않고, 결정론적 시스템(System)과 확률론적 AI(Agent)의 역할을 엄격히 분리한 **Micro-tasking 기반의 하이브리드 아키텍처**를 채택했습니다.

## 1. 도구 선택 이유

MVP의 빠른 검증과 향후 프로덕션 레벨로의 확장성을 동시에 고려하여 도구를 선정했습니다.

* **Data Processing: Python (Pandas) & JSON**
    * **선택 이유:** 이커머스의 뷰티 도메인은 고객의 복합적인 피부 고민과 상품의 다중 태그를 교차 분석해야 합니다. 초기 MVP 단계에서 RDBMS를 구축하는 대신, Python의 `Set` 연산과 Pandas의 유연한 DataFrame을 활용하여 인메모리 상에서 하드 필터링 로직을 구현했습니다. 이는 민첩한 테스트를 가능하게 하며, 향후 SQL 기반의 DB(PostgreSQL 등)로 마이그레이션하기 용이한 구조입니다.
* **Frontend & Serving: Streamlit**
    * **선택 이유:** Python 백엔드 로직과 LLM API를 가장 직관적으로 연결하고, 결과를 시각화하기 위해 선택했습니다. Streamlit Cloud를 통해 별도의 인프라 구축 없이 즉각적인 라이브 배포가 가능합니다.
* **LLM Orchestration: Multi-Agent 협업 체제**
    * **설계 (Gemini 3.1 Pro):** 깊은 추론 능력을 활용해 데이터 스키마 및 프롬프트 로직 설계.
    * **데이터 생성 및 검수 (Gemini 3.1 Pro):** 뷰티 도메인 리서치 및 현실적인 Mock-up 데이터(JSON) 생성.
    * **지엽적 기능 구현 및 테스트 (Gemini 3.1 Pro):** 세션 히스토리에 구축된 도메인 컨텍스트를 재활용하여, 프로젝트 의도에 부합하는 세부 기능을 신속하게 구현함.
    * **LLM API (Anthropic API):** Claude Code CLI 환경과의 네이티브 연동 및 최적의 호환성을 확보하여, 지연 없는 Agentic Workflow를 구축하기 위해 선택
    * **구현 및 오케스트레이션 (Claude Sonnet 4.6):** 우수한 코딩 정확도를 바탕으로 Streamlit 및 Python 로직 구현.
    * **의의:** AI를 단순 도구가 아닌 '목적별 전문가 조직'으로 오케스트레이션하여 산출물의 품질을 극대화했습니다.

## 2. 데이터 흐름 (Data Flow: The H-A-S Model)

사용자(Human)의 불확실한 자연어를 Agent가 정형 데이터로 변환하고, System이 팩트 기반의 데이터를 추출하는 **H-A-S (Human - Agent - System) 파이프라인**으로 동작합니다.

1.  **Intent Parsing (H → A):** 사용자가 자연어로 검색("민감성 피부 진정 마스크팩")하면, Agent가 이를 파싱하여 검색용 파라미터(JSON)를 생성합니다. `{"skin_type": "sensitive", "effect": "calming", "category": "mask"}`
2.  **Deterministic Retrieval (A → S):** System(Pandas)이 JSON 파라미터를 받아 `products.json`에서 정확히 일치하는 상품만 필터링합니다. (환각 원천 차단)
3.  **Fact-based Summarization (S → A):** 사용자가 특정 상품을 선택하면, System이 `reviews.json`에서 '해당 사용자와 동일한 피부 타입'의 리뷰만 추출합니다. Agent는 이 제한된 팩트 데이터만을 바탕으로 장단점을 요약합니다.
4.  **Cross-selling Action (S → A → H):** `logs.json`의 동시 구매 이력을 분석하여 System이 시너지 상품을 도출하면, Agent가 개인화된 추천 멘트와 함께 최종 제안합니다.

## 3. 예상 비용 (Expected Costs)

효율적인 데이터 흐름 설계를 통해 LLM API 토큰 비용을 절감하는 데 초점을 맞췄습니다. 전체 상품/리뷰 DB를 프롬프트에 넣는 RAG 방식과 달리, **System이 1차 필터링한 소량의 데이터만 LLM에 전달**하므로 비용 효율성이 극대화됩니다.

**[MVP 구축 및 테스트 단계]**
* **인프라 비용:** $0 (Streamlit Cloud 무료 티어 활용)
* **AI 서비스 비용:** $5(Claude 유료 Plan 구독료)
* **LLM API 호출 및 Mock-up 데이터 생성:** $5 (Anthropic API credit 충전).
