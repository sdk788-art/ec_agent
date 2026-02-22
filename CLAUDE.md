# CLAUDE.md — ec_agent (Beauty E-Commerce AI Agent)

This file provides guidance for AI assistants working on this codebase.

---

## Project Overview

**ec_agent** is a Korean beauty e-commerce AI agent. It provides:

- Skin-type-aware natural language product search
- AI-summarized customer reviews filtered by similar skin types
- Cross-selling recommendations based on co-purchase history

The project is **fully implemented and deployed on Streamlit Cloud**. All application
code (`app.py`, `agents.py`, `logic.py`, `requirements.txt`) exists and is production-ready.

---

## Architecture: The H-A-S Model

The core design principle is strict separation between probabilistic (AI) and deterministic
(System) tasks to eliminate hallucinations.

```
Human  →  Agent  →  System  →  Agent  →  Human
(natural  (parse    (pandas    (summarize  (output)
 language)  intent)   filter)    facts)
```

| Role   | Responsibility                                                          | Implementation       |
|--------|-------------------------------------------------------------------------|----------------------|
| Human  | Natural language input / UI interaction                                 | Streamlit widgets    |
| Agent  | Probabilistic tasks: intent parsing, summarization, recommendations     | Anthropic Claude API |
| System | Deterministic tasks: DB filtering, quantitative metrics                 | Python / Pandas      |

**Critical rule:** The LLM (Agent) must only receive pre-filtered, fact-based data from
the System. Never pass the full database to the LLM. This prevents hallucination and
controls API token costs.

### 9-Step Micro-task Workflow

| Step | Actor  | Action |
|------|--------|--------|
| 1 | Human  | Enter natural language or keyword search (e.g., "민감성 피부 진정 마스크팩") |
| 2 | Agent  | Parse query → produce search parameter JSON `{"product_type": "sheet_mask", "concerns": ["redness"]}` |
| 3 | System | Filter `products.json` using the parameter JSON; display results with one-line representative review |
| 4 | Human  | Select a product from results |
| 5 | System | Extract reviews from `reviews.json` for customers with matching skin type; compute quantitative metrics |
| 6 | Agent  | Summarize the filtered reviews and metrics (e.g., "80% of dry-skin users were satisfied with moisturization") |
| 7 | Human  | Read product page or add to cart |
| 8 | System | Query `logs.json` for frequently co-purchased products |
| 9 | Agent  | Generate personalized cross-sell recommendation message |

---

## Directory Structure

```
ec_agent/
├── data/                   # Mock databases (JSON, read-only during MVP)
│   ├── customers.json      # 50 customer records
│   ├── products.json       # 48 product records
│   ├── logs.json           # 778 customer action logs
│   └── reviews.json        # 205 customer reviews (Korean text)
├── docs/                   # Design documentation (written in Korean)
│   ├── architecture.md     # Tool choices and H-A-S data flow rationale
│   ├── functional_spec.md  # Feature-level task definitions
│   └── table_def.md        # Full schema with Pandas/SQL types and constraints
├── app.py                  # Streamlit main entry point + UI routing (~545 lines)
├── agents.py               # LLM orchestration layer — 3 agent functions (~169 lines)
├── logic.py                # System filtering & data aggregation — 5 functions (~213 lines)
├── requirements.txt        # Python dependencies (4 packages)
├── CLAUDE.md               # This file
└── README.md               # Project introduction (Korean)
```

---

## Data Model

All data is stored as JSON arrays and loaded into Pandas DataFrames at runtime via
`@st.cache_data` in `logic.py`. See `docs/table_def.md` for the full schema.

### Customer DB — `data/customers.json`

| Column | Type | Allowed Values |
|---|---|---|
| `customer_id` | int (PK) | unique |
| `gender` | category | `'male'`, `'female'`, `'other'` |
| `age` | int | >= 0 |
| `base_skin_type` | category | `'dry'`, `'normal'`, `'oily'`, `'combination'`, `'dehydrated_oily'` |
| `is_sensitive` | bool | `True`, `False` |
| `skin_concerns` | list | `'acne_trouble'`, `'pores'`, `'wrinkles_aging'`, `'pigmentation_blemish'`, `'redness'`, `'severe_dryness'`, `'dullness'` |

### Product DB — `data/products.json`

| Column | Type | Allowed Values |
|---|---|---|
| `product_id` | int (PK) | unique |
| `product_name` | str | — |
| `brand` | str | — |
| `price` | int | >= 0 (KRW) |
| `stock` | int | >= 0 |
| `product_type` | category | `'cleansing_foam'`, `'cleansing_oil_water'`, `'exfoliator_peeling'`, `'toner'`, `'toner_pad'`, `'essence'`, `'serum'`, `'ampoule'`, `'lotion_emulsion'`, `'moisture_cream'`, `'eye_cream'`, `'face_oil'`, `'sheet_mask'`, `'wash_off_mask'`, `'sun_care'`, `'lip_care'` |
| `target_skin_types` | list | same values as `base_skin_type` |
| `target_concerns` | list | same values as `skin_concerns` |
| `description` | str | representative one-line review |

### Log DB — `data/logs.json`

| Column | Type | Notes |
|---|---|---|
| `log_id` | str UUID (PK) | unique |
| `customer_id` | int (FK → customers) | — |
| `product_id` | int (FK → products) | — |
| `action_type` | category | `'view'`, `'cart'`, `'purchase'` |
| `dwell_time` | float | seconds; valid only for `'view'` actions |
| `timestamp` | datetime | ISO format `YYYY-MM-DD HH:MM:SS` |

### Review DB — `data/reviews.json`

| Column | Type | Notes |
|---|---|---|
| `review_id` | str UUID (PK) | unique |
| `purchase_log_id` | str UUID (FK → logs, unique) | verifies purchase before review |
| `customer_id` | int (FK → customers) | — |
| `product_id` | int (FK → products) | — |
| `rate` | float | 1.0–5.0, increments of 0.5 |
| `review` | str (nullable) | Korean-language review text |
| `created_at` | datetime | must be after purchase timestamp |

---

## Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Streamlit | Deployed on Streamlit Cloud (free tier) |
| Data processing | Python + Pandas | In-memory JSON → DataFrame via `@st.cache_data` |
| LLM | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) | All three agent functions; chosen for cost efficiency |
| Config | python-dotenv | `load_dotenv()` in `agents.py` loads `ANTHROPIC_API_KEY` |
| Storage (MVP) | JSON files | Migrate to PostgreSQL post-MVP |

---

## Implemented Application Code

### `requirements.txt`

```
streamlit
pandas
anthropic
python-dotenv
```

### Module Responsibilities

| File | Responsibility |
|---|---|
| `app.py` | Streamlit UI, page routing (`search` ↔ `detail`), session state, callback functions |
| `agents.py` | All LLM calls (3 functions), Korean ↔ English label mappings, Anthropic client init |
| `logic.py` | Data loading (`@st.cache_data`), all Pandas filter/aggregate functions (5 functions) |

### Session State Keys (`app.py`)

| Key | Type | Purpose |
|---|---|---|
| `current_customer` | dict \| None | Logged-in customer record |
| `search_results` | DataFrame \| None | Filtered products from last search |
| `selected_product_id` | int \| None | Product selected for detail view |
| `parsed_params` | dict \| None | Agent-parsed search parameter JSON |
| `last_search_query` | str | Last search string (LLM cache invalidation trigger) |
| `cart_added` | set[int] | Set of product IDs added to cart |
| `current_page` | str | Page routing: `"search"` or `"detail"` |
| `list_page` | int | Current pagination page number (1-indexed) |
| `sort_by` | str | Sort label: `"평점순"`, `"후기 많은순"`, `"판매량 순"`, `"낮은 가격순"`, `"높은 가격순"` |
| `review_summary_{pid}_{skin}` | str \| None | Cached LLM review summary per product+skin type |
| `cross_msg_{pid}_{cid}` | str \| None | Cached LLM cross-sell message per product+customer |

### Agent Functions (`agents.py`)

All three functions follow the H-A-S principle — they receive only pre-filtered data:

```python
def agent_parse_intent(query: str) -> dict:
    """Micro-task 2: H → A. Converts natural language query to JSON params.
    Returns: {"product_type": str | null, "concerns": list[str]}
    Model: claude-haiku-4-5-20251001, max_tokens=256
    Handles LLM wrapping output in ```json...``` fences automatically.
    """

def agent_summarize_reviews(
    filtered_reviews_df: pd.DataFrame,
    skin_type: str,
    metrics: dict,          # {"total_reviews": int, "avg_rate": float, "satisfaction_pct": float}
) -> str | None:
    """Micro-task 6: S → A. Summarizes pre-filtered same-skin-type reviews.
    Returns None if no text reviews exist (avoids unnecessary API call).
    Model: claude-haiku-4-5-20251001, max_tokens=512
    Output: Korean, 2-3 sentences.
    """

def agent_recommend_cross_sell(
    selected_product: pd.Series,
    cross_sell_df: pd.DataFrame,
    customer: dict,
) -> str:
    """Micro-task 9: S → A. Generates cross-sell recommendation message.
    Model: claude-haiku-4-5-20251001, max_tokens=512
    Output: Korean, 2-3 sentences.
    """
```

Also exports Korean label mapping dicts used by `app.py`:
- `SKIN_TYPE_KO` — `base_skin_type` → Korean display string
- `SKIN_CONCERN_KO` — concern key → Korean display string
- `PRODUCT_TYPE_KO` — `product_type` → Korean display string

### System Filter Functions (`logic.py`)

All functions are deterministic Pandas operations with no LLM involvement:

```python
@st.cache_data
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Loads all 4 JSON files into DataFrames. Called once at module import."""

def system_aggregate_product_stats(products_df: pd.DataFrame) -> pd.DataFrame:
    """Appends avg_rating, review_count, sales_volume columns via left-join.
    Null-fills with 0 for products with no review/purchase history.
    """

def system_filter_products(params: dict, customer: dict) -> pd.DataFrame:
    """Micro-task 3: A → S. Three-stage Pandas filter:
      1. product_type   — exact match (from LLM params)
      2. target_skin_types — set membership (from customer.base_skin_type)
      3. target_concerns   — set-intersection of (LLM concerns ∪ customer concerns)
    Returns filtered DataFrame with stats columns appended.
    """

def system_get_same_skin_reviews(
    product_id: int, skin_type: str
) -> tuple[pd.DataFrame, dict]:
    """Micro-task 5: S → A preparation. Filters same-skin-type reviews.
    Computes metrics dict: {"total_reviews", "avg_rate", "satisfaction_pct"}.
    Samples max 5 most-recent reviews; truncates each to 300 chars.
    """

def system_get_cross_sell_products(selected_id: int, top_n: int = 2) -> pd.DataFrame:
    """Micro-task 8: S → A preparation. Co-purchase frequency analysis.
    Returns top_n products most frequently co-purchased with selected_id.
    """
```

Array-valued columns (`target_skin_types`, `target_concerns`, `skin_concerns`) may be
stored as JSON strings in older Pandas versions. The `_to_list()` utility in `logic.py`
handles both `list` and `str` representations safely.

### UI Patterns (`app.py`)

**Page routing** — `st.session_state.current_page` holds `"search"` or `"detail"`.
Transitions happen via `on_click` callbacks, not conditional re-renders, so a single
click always produces the correct page transition:

```python
def _cb_select_product(pid: int) -> None:
    st.session_state.selected_product_id = pid
    st.session_state.current_page = "detail"

def _cb_back_to_search() -> None:
    st.session_state.current_page = "search"
```

**LLM result caching** — review summaries and cross-sell messages are stored in
session state under dynamic keys (`review_summary_{pid}_{skin}`,
`cross_msg_{pid}_{cid}`). `_clear_llm_caches()` deletes all such keys on new search
queries or customer login/logout.

**Pagination** — `_PAGE_SIZE = 10`. Navigation via `_cb_prev_page()` /
`_cb_next_page(max_page)` callbacks. Sort changes reset `list_page` to 1.

---

## Development Workflow

### Running the application

```bash
# Install dependencies
pip install -r requirements.txt

# Set API key (or use a .env file — python-dotenv loads it automatically)
export ANTHROPIC_API_KEY=sk-ant-...

# Run locally
streamlit run app.py
```

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic Claude API access |

`agents.py` calls `load_dotenv()` at import time, so a `.env` file in the project root
is automatically picked up. Never commit API keys. `.gitignore` excludes `.env`,
`.envrc`, and `.streamlit/secrets.toml`.

### Git branches

- `master` — stable/main branch
- `claude/...` — AI-assistant working branches

---

## Naming Conventions

- All column names and JSON keys: `snake_case`
- IDs for master data (customers, products): `int`
- IDs for transactional data (logs, reviews): UUID strings
- Categorical values: lowercase English with underscores (e.g., `'dehydrated_oily'`, `'acne_trouble'`)
- Session state cache keys: `review_summary_{product_id}_{skin_type}`, `cross_msg_{product_id}_{customer_id}`

---

## Key Design Constraints

1. **Never pass the full database to the LLM.** The System always filters first; the Agent only sees the subset.
2. **Do not add a database until post-MVP.** JSON + Pandas in-memory is intentional for rapid iteration.
3. **Streamlit is the only frontend.** No React, no Flask. UI and backend live in `app.py`.
4. **Mock data is read-only** during MVP (all four JSON files).
5. **Review text is Korean.** All three agent functions output Korean. Prompts handle Korean input natively.
6. **Use `on_click` callbacks for all state-mutating buttons.** Never use bare `if st.button(...)` blocks for page transitions — they cause double-rerender issues.
7. **LLM model is `claude-haiku-4-5-20251001`.** Do not switch to Sonnet/Opus unless token limits require it — Haiku is sufficient and significantly cheaper for this use case.

---

## Future Roadmap (post-MVP)

- Migrate from JSON to PostgreSQL; replace Pandas filters with SQL queries
- Add collaborative filtering for smarter cross-sell recommendations
- Implement search log storage in `logs.json` (currently only view/cart/purchase are logged)
- Add new customer registration (currently login is selector-based; `customers.json` is read-only)
- Persist cart across sessions (currently session-only `set`)
