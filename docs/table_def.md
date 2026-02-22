## 테이블 정의서

#### 1. Customer DB (고객 정보 테이블)
고객의 기본 인구통계학적 정보와 도메인 전문가가 정의한 피부 타입 및 고민 속성을 통합했습니다. 고객이 여러 피부 고민을 가질 수 있으므로 skin_concerns는 배열(Array) 형태로 구성하여 유연성을 확보했습니다.
| 컬럼명 (snake_case) | 데이터 타입 (Pandas / SQL) | 제약조건 및 허용값 (Categorical Values) | 설명 |
| --- | --- | --- | --- |
| `customer_id` | `int64` / `INT` | Primary Key, Not Null, Unique | 고객 고유 식별자 |
| `gender` | `category` / `VARCHAR(10)` | 'male', 'female', 'other' | 고객 성별 |
| `age` | `int32` / `INT` | `age >= 0` | 고객 나이 |
| `base_skin_type` | `category` / `VARCHAR(20)` | 'dry', 'normal', 'oily', 'combination', 'dehydrated_oily' | 기본 피부 타입 (단일 선택) |
| `is_sensitive` | `bool` / `BOOLEAN` | True, False | 민감성 피부 여부 |
| `skin_concerns` | `object(list)` / `ARRAY<VARCHAR>` | 'acne_trouble', 'pores', 'wrinkles_aging', 'pigmentation_blemish', 'redness', 'severe_dryness', 'dullness' | 피부 고민 (다중 선택 가능, 배열) |
---

#### 2. Product DB (상품 정보 테이블)

AI 추천 에이전트가 고객의 피부 타입/고민과 상품을 빠르게 매칭(하드 필터링)할 수 있도록 `target_skin_types`와 `target_concerns` 컬럼을 배열로 배치한 아키텍처 요구사항을 완벽히 수용했습니다.

| 컬럼명 (snake_case) | 데이터 타입 (Pandas / SQL) | 제약조건 및 허용값 (Categorical Values) | 설명 |
| --- | --- | --- | --- |
| `product_id` | `int64` / `INT` | Primary Key, Not Null, Unique | 상품 고유 식별자 |
| `product_name` | `object(str)` / `VARCHAR(255)` | Not Null | 상품명 |
| `brand` | `object(str)` / `VARCHAR(100)` | Not Null | 브랜드명 |
| `price` | `int32` / `INT` | `price >= 0` | 상품 판매 가격 |
| `stock` | `int32` / `INT` | `stock >= 0` | 현재 재고 수량 |
| `product_type` | `category` / `VARCHAR(50)` | 'cleansing_foam', 'cleansing_oil_water', 'exfoliator_peeling', 'toner', 'toner_pad', 'essence', 'serum', 'ampoule', 'lotion_emulsion', 'moisture_cream', 'eye_cream', 'face_oil', 'sheet_mask', 'wash_off_mask', 'sun_care', 'lip_care' | 상품 카테고리 (스킨케어 표준 분류 16종) |
| `target_skin_types` | `object(list)` / `ARRAY<VARCHAR>` | Customer DB의 `base_skin_type` 허용값과 동일 | 해당 상품이 적합한 타겟 피부 타입들 (배열) |
| `target_concerns` | `object(list)` / `ARRAY<VARCHAR>` | Customer DB의 `skin_concerns` 허용값과 동일 | 해당 상품이 해결할 수 있는 타겟 피부 고민들 (배열) |
| `description` | `object(str)` / `TEXT` | Nullable | 상품에 대한 상세 설명 (AI 컨텍스트 및 UI 노출용) |
---

#### 3. Log DB (고객 행동 로그 테이블)

추천 시스템의 성능을 평가하고 향후 협업 필터링(Collaborative Filtering) 등의 알고리즘 고도화에 필수적인 유저 행동 추적 테이블입니다. 체류 시간(`dwell_time`)을 포함하여 암시적 피드백(Implicit Feedback)을 정교하게 수집할 수 있습니다.

| 컬럼명 (snake_case) | 데이터 타입 (Pandas / SQL) | 제약조건 및 허용값 (Categorical Values) | 설명 |
| --- | --- | --- | --- |
| `log_id` | `object(str)` / `VARCHAR(50)` | Primary Key, Not Null, Unique (UUID 권장) | 로그 고유 식별자 |
| `customer_id` | `int64` / `INT` | Foreign Key (Customer DB 참조) | 행동을 수행한 고객 ID |
| `product_id` | `int64` / `INT` | Foreign Key (Product DB 참조) | 대상 상품 ID |
| `action_type` | `category` / `VARCHAR(20)` | 'view', 'cart', 'purchase' | 고객 행동 유형 |
| `dwell_time` | `float64` / `FLOAT` | `dwell_time >= 0.0` (단위: 초) | 해당 상품 페이지 체류 시간 (view 액션 시 유효) |
| `timestamp` | `datetime64[ns]` / `TIMESTAMP` | Not Null, `YYYY-MM-DD HH:MM:SS` 포맷 | 행동 발생 일시 |
---

#### 4. Review DB (고객 리뷰 및 평점 테이블)
Log DB의 구매 기록을 참조하게 하여, 추천 시스템에서 '실제 구매 데이터에 기반한 고품질 리뷰'인지 검증할 수 있도록 연결 고리를 만들었습니다.

| 컬럼명 (snake_case) | 데이터 타입 (Pandas / SQL) | 제약조건 및 허용값 (Categorical Values) | 설명 |
| --- | --- | --- | --- |
| `review_id` | `object(str)` / `VARCHAR(50)` | Primary Key, Not Null, Unique (UUID 권장) | 리뷰 고유 식별자 |
| `purchase_log_id` | `object(str)` / `VARCHAR(50)` | Foreign Key, Unique | 리뷰가 작성된 원본 구매 로그의 `log_id`. 실제 구매 여부 검증용 |
| `customer_id` | `int64` / `INT` | Foreign Key (Customer DB 참조) | 리뷰를 작성한 고객 ID |
| `product_id` | `int64` / `INT` | Foreign Key (Product DB 참조) | 평가 대상 상품 ID |
| `rate` | `float64` / `FLOAT` | `1.0 <= rate <= 5.0` (0.5 단위 허용) | 고객 부여 평점 (예: 4.5, 5.0) |
| `review` | `object(str)` / `TEXT` | Nullable (평점만 남기고 텍스트는 안 쓸 경우 대비) | 고객이 작성한 리뷰 텍스트 내용 |
| `created_at` | `datetime64[ns]` / `TIMESTAMP` | Not Null, `YYYY-MM-DD HH:MM:SS` | 리뷰 작성 일시 (구매 일시 이후여야 함) |
---

