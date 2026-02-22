# ec_agent(E_Commerce_Agent)

### 본 프로젝트는 뷰티 E-commerce Agent의 아이디어를 MVP로 구현한 것입니다.

### 아이디어 개요

- 사용자 피부타입을 정보로 받음

- 문장형 검색(민감성 피부인데, 진정효과가 있는 마스크팩 찾아줘)

- 검색결과에서 제품별로 유사한 피부타입 고객 후기 모음 및 요약하여 제시

- 특정제품 선택 시 해당 제품과 시너지 제품 추천(다른 고객이 같이 많이 구매한 제품 등)

- 고객 정보 테이블, 상품정보 테이블, 고객의 행동정보(구매이력, 페이지 체류시간, 검색기록 등)을 분리된 데이터로 처리



### 목업 데이터(DB) 구성

- **고객 DB:** id, 성별, 연령, 피부타입 등

- **상품 DB:** 유형, 가격, 재고수량, 브랜드, 기능 등

- **로그 DB:** 구매이력, 페이지뷰, 장바구니 등

- **리뷰 DB:** 평점(5점만점), 주관식 리뷰 등


### 구현 Flow(micro-task)

  0. **human은 사용자, agent는 확률론적 task, system은 결정론적 task.**
  1. Human, 문장형 또는 키워드형 검색어 입력(ex: 민감성 피부 개선용 마스크팩, 건성 피부 데일리 크림)
  2. Agent, 제품 검색용 json 생성
  3. System, json기반으로 DB에서 적절한 상품을 필터링하여 검색 결과 노출 (상품 DB에 저장된 대표 후기 한줄이 기본적으로 노출)
  4. Human, 노출된 검색결과에서 원하는 제품 선택
  5. System, 동일 피부타입을 가진 이전 구매자들의 후기 추출 및 정량지표 생성
  6. Agent, 추출된 후기 및 정량지표를 적절하게 요약(ex: 건성 피부 사용자 80%가 수분감에 만족했어요. 민감성 피부 사용자 중 일부가 따가움을 느꼈다고 하니 주의해주세요.)
  7. Human, 해당 제품 페이지를 충분히 읽거나, 장바구니에 담음.
  8. System, 함께 구매한 빈도가 높은 제품을 DB로부터 선별
  9. Agent, 페어링 제품 추천 (ex: 이 두 제품을 같이 쓰면 민감성 케어 완성도가 200% 높아집니다.)

### 디렉토리 구조
#### 본 프로젝트는 데이터, 문서, 실행 코드, AI 프롬프트 로그를 명확히 분리하여 관리함

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
├── .gitignore                 # Git 버전 관리 제외 목록 (.env, __pycache__ 등)
├── app.py                     # [UI 계층] Streamlit 메인 화면 및 상태(Session) 관리
├── agents.py                  # [Agent 계층] LLM 프롬프트 제어 및 Anthropic API 호출
├── logic.py                   # [System 계층] 데이터 로드 및 Pandas 교차 연산 필터링
├── generate_mock_data.py      # 목업 데이터 대량 생성 및 스케일업 자동화 스크립트
├── CLAUDE.md                  # AI 에이전트(Claude Code) 전용 시스템 지침 및 컨텍스트
├── requirements.txt           # 패키지 의존성 명세
└── README.md                  # 프로젝트 소개, 실행 가이드 및 아키텍처 요약
```
