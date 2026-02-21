# ec_agent(E_Commerce_Agent)

### 디렉토리 구조
#### 본 프로젝트는 데이터, 문서, 실행 코드, AI 프롬프트 로그를 명확히 분리하여 관리함

```text
my-ecommerce-agent/
├── data/                  # 목업 데이터 (JSON)
│   ├── customers.json     # 고객 데이터 (50 rows)
│   ├── logs.json          # 로그 데이터 (778 rows)
│   ├── products.json      # 상품 데이터 (48 rows)
│   └── reviews.json       # 리뷰 데이터 (205 rows)
├── docs/                  # 아키텍처 및 기획 문서
│   ├── architecture.md    # 아키텍처 메모
│   └── table_def.md       # 테이블 정의서
├── app.py                 # Streamlit 메인 실행 파일
├── requirements.txt       # 패키지 의존성 관리
└── README.md              # 프로젝트 소개 및 가이드
```
