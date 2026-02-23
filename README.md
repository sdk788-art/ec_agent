# Beauty E-Commerce AI Agent (B2B PoC)

본 프로젝트는 뷰티 E-Commerce 특성을 반영한 AI 추천 에이전트를 MVP(Minimum Viable Product)로 구현한 PoC입니다. 
단순한 챗봇을 넘어, LLM의 한계(Hallucination, 비용, 지연 시간)를 통제하고 실제 비즈니스에 투입 가능한 수준의 **'결정론적 AI 시스템'**을 검증하는 데 목적이 있습니다.

## 핵심 아키텍처: H-A-S 모델 도입
LLM에게 모든 검색과 추천을 맡기지 않고, 역할을 3단계로 엄격히 분리하여 신뢰할 수 있는 결과를 보장합니다.
* **Human (사용자):** 자연어 발화 및 UI 상호작용
* **Agent (확률론적 Task):** LLM을 활용한 의도 파싱(Intent Parsing) 및 문맥 기반 리뷰 요약, 시너지 메시지 생성
* **System (결정론적 Task):** Agent가 추출한 파라미터 기반의 정밀한 DB 필터링 및 교차 연산 로직

## 핵심 트러블슈팅 및 비즈니스 최적화 (Key Takeaways)

### 1. UX/UI 최적화: SPA(Single Page Application) 라우팅 도입
* **Problem:** 한 화면 내에서 동적 Expander 및 JS 기반 스크롤 도입 시, 프레임워크 렌더링 지연으로 인한 불안정성 발생.
* **Solution:** B2B 대시보드 환경에 적합한 **SPA 라우팅 패턴**으로 UI 아키텍처 전면 개편. `session_state`를 활용해 '목록 뷰'와 '상세 뷰'를 완벽히 격리하여 직관적이고 즉각적인 화면 전환 UX 달성.

### 2. 비용 및 지연 시간 최적화 (Token Optimization)
* **Problem:** 대규모 스케일업 환경(리뷰 수천 건)에서, 특정 상품의 모든 리뷰를 LLM에 전달할 경우 심각한 API 비용 낭비와 응답 지연 발생 위험.
* **Solution:** System 계층에서 고객과 동일 피부 타입의 리뷰만 1차 필터링 후, **Top N건만 샘플링 및 텍스트 절사(Truncation)** 처리하여 프롬프트에 주입. 환각을 방지하고 요약 속도 개선.

### 3. 콜드 스타트(Cold Start) 및 엣지 케이스 방어
* **Problem:** 리뷰가 0건인 신규 상품 노출 시, AI가 무의미한 요약을 시도하거나 레이아웃이 깨지는 현상.
* **Solution:** System 단에서 리뷰 건수를 선행 체크하고, 데이터가 부족한 경우 Agent API 호출을 원천 차단하여 비용 세이브. 화면에는 우아한 Fallback UI(`"리뷰가 아직 없습니다"`)를 노출하여 엣지 케이스 방어.

---

## 구현 Flow (9-Step Micro-tasks)
**LLM은 사전에 System이 필터링한 데이터만 전달받으며, 전체 DB에 절대 직접 접근하지 않습니다.**

0. **Rule:** human은 사용자, agent는 확률론적 task, system은 결정론적 task.
1. **Human:** 문장형 또는 키워드형 검색어 입력 (ex: "민감성 피부 개선용 마스크팩")
2. **Agent:** 검색어에서 파라미터를 추출하여 제품 검색용 JSON 생성
3. **System:** JSON 기반으로 DB에서 적절한 상품을 결정론적으로 필터링하여 검색 결과 노출
4. **Human:** 노출된 검색결과에서 원하는 제품 선택
5. **System:** 해당 고객과 동일 피부타입을 가진 이전 구매자들의 후기 추출 및 정량지표(평점 등) 연산
6. **Agent:** 추출된 타겟 후기 및 지표를 바탕으로 피부 타입 맞춤형 요약 생성
7. **Human:** 상세 리뷰를 읽고 장바구니에 담음
8. **System:** 로그 DB를 분석하여 해당 제품과 함께 구매한 빈도가 높은 시너지 제품 선별
9. **Agent:** 선별된 상품과 고객 고민을 매칭하여 개인화된 페어링 추천 메시지 작성

---

## Tech Stack
* **Frontend:** Streamlit 
* **Data Processing:** Python + Pandas
* **LLM:** Anthropic Claude Haiku 4.5
* **Data Storage:** JSON (대규모 목업 데이터)

## 디렉토리 구조 및 데이터 스케일
데이터, 문서, 실행 코드, AI 프롬프트 로그를 명확히 분리하여 관리합니다.
```text
my-ecommerce-agent/
├── data/                      # 대규모 목업 데이터 (JSON)
│   ├── customers.json         # 고객 데이터 (200 rows)
│   ├── logs.json              # 유저 행동 로그 (6,188 rows)
│   ├── products.json          # 뷰티 상품 데이터 (512 rows)
│   └── reviews.json           # 상품별 고객 리뷰 (1,503 rows)
├── docs/                      # 기획 및 설계 문서
│   ├── architecture.md        # H-A-S 아키텍처 설계 메모
│   ├── functional_spec.md     # 기능 명세서
│   └── table_def.md           # 테이블 및 스키마 정의서
├── .env                       # (로컬 전용) API Key 등 환경변수 보관 (Git 추적 제외)
├── .gitignore                 # Git 버전 관리 제외 목록
├── app.py                     # [UI 계층] Streamlit 메인 화면 및 상태(Session) 라우팅 관리
├── agents.py                  # [Agent 계층] LLM 프롬프트 제어 및 Anthropic API 호출
├── logic.py                   # [System 계층] 데이터 로드 및 Pandas 교차 연산 필터링
├── generate_mock_data.py      # 목업 데이터 대량 생성 및 스케일업 자동화 스크립트
├── CLAUDE.md                  # AI 에이전트 전용 시스템 지침 및 컨텍스트
├── requirements.txt           # 패키지 의존성 명세
└── README.md                  # 프로젝트 소개 및 아키텍처 요약
