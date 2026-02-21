# CLAUDE.md — ec_agent (Beauty E-Commerce AI Agent)

This file provides guidance for AI assistants working on this codebase.

---

## Project Overview

**ec_agent** is a Korean beauty e-commerce AI agent implemented as an MVP. It provides:

- Skin-type-aware natural language product search
- AI-summarized customer reviews filtered by similar skin types
- Cross-selling recommendations based on co-purchase history

The project is currently in the **documentation and data phase** — all four mock databases are fully defined and populated, but the application code (`app.py`, `requirements.txt`) has not been implemented yet. The primary next task is implementing the Streamlit application.

---

## Architecture: The H-A-S Model

The core design principle is strict separation between probabilistic (AI) and deterministic (System) tasks to eliminate hallucinations.

```
Human  →  Agent  →  System  →  Agent  →  Human
(natural  (parse    (pandas    (summarize  (output)
 language)  intent)   filter)    facts)
```

| Role   | Responsibility                                          | Implementation       |
|--------|---------------------------------------------------------|----------------------|
| Human  | Natural language input / UI interaction                 | Streamlit widgets    |
| Agent  | Probabilistic tasks: intent parsing, summarization, recommendations | Anthropic Claude API |
| System | Deterministic tasks: DB filtering, quantitative metrics | Python / Pandas      |

**Critical rule:** The LLM (Agent) must only receive pre-filtered, fact-based data from the System. Never pass the full database to the LLM. This prevents hallucination and controls API token costs.

### 9-Step Micro-task Workflow

| Step | Actor  | Action |
|------|--------|--------|
| 1 | Human  | Enter natural language or keyword search (e.g., "민감성 피부 진정 마스크팩") |
| 2 | Agent  | Parse query → produce search parameter JSON `{"skin_type": "sensitive", "effect": "calming", "category": "mask"}` |
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
├── app.py                  # (TO BE CREATED) Streamlit main entry point
├── requirements.txt        # (TO BE CREATED) Python dependencies
├── CLAUDE.md               # This file
└── README.md               # Project introduction (Korean)
```

---

## Data Model

All data is stored as JSON arrays and loaded into Pandas DataFrames at runtime. See `docs/table_def.md` for the full schema.

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
| Frontend | Streamlit | Deploy via Streamlit Cloud (free tier) |
| Data processing | Python + Pandas | In-memory JSON → DataFrame; set operations for filtering |
| LLM | Anthropic Claude (Sonnet 4.6) | Intent parsing, review summarization, cross-sell copy |
| Storage (MVP) | JSON files | Migrate to PostgreSQL post-MVP |

---

## Implementing the Application

### Required files to create

**`requirements.txt`** — minimum dependencies:
```
streamlit
pandas
anthropic
```

**`app.py`** — Streamlit entry point following the H-A-S workflow:

```python
import streamlit as st
import pandas as pd
import json
import anthropic

# Load data
customers = pd.read_json("data/customers.json")
products  = pd.read_json("data/products.json")
logs      = pd.read_json("data/logs.json")
reviews   = pd.read_json("data/reviews.json")

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
```

### Session state keys (Streamlit)

Use `st.session_state` to persist across reruns:

| Key | Purpose |
|---|---|
| `current_customer` | loaded customer record (dict) after login |
| `search_results` | filtered product DataFrame from last search |
| `selected_product_id` | product selected for detail view |

### Agent function pattern

All LLM calls must follow this pattern — pass only pre-filtered data:

```python
def agent_parse_intent(query: str) -> dict:
    """H → A: Convert natural language to search params."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[{"role": "user", "content": f"Parse this query into JSON: {query}"}]
    )
    return json.loads(response.content[0].text)

def system_filter_products(params: dict, products_df: pd.DataFrame) -> pd.DataFrame:
    """A → S: Deterministic Pandas filtering — no LLM involved."""
    mask = products_df["target_skin_types"].apply(lambda x: params["skin_type"] in x)
    return products_df[mask]

def agent_summarize_reviews(filtered_reviews: list[dict], skin_type: str) -> str:
    """S → A: Summarize only the pre-filtered review subset."""
    review_text = "\n".join(r["review"] for r in filtered_reviews if r.get("review"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": f"Summarize these {skin_type} skin reviews:\n{review_text}"}]
    )
    return response.content[0].text
```

### System filter functions (Pandas patterns)

Array-valued columns (`target_skin_types`, `target_concerns`, `skin_concerns`) require set-intersection filtering:

```python
# Filter products matching skin type
products[products["target_skin_types"].apply(lambda x: skin_type in x)]

# Filter products matching ANY concern in user's list
user_concerns = {"acne_trouble", "pores"}
products[products["target_concerns"].apply(lambda x: bool(set(x) & user_concerns))]

# Get same-skin-type reviews for a product
same_type_customer_ids = customers[customers["base_skin_type"] == skin_type]["customer_id"]
product_reviews = reviews[
    (reviews["product_id"] == product_id) &
    (reviews["customer_id"].isin(same_type_customer_ids))
]

# Co-purchase cross-sell
purchase_logs = logs[logs["action_type"] == "purchase"]
co_purchases = purchase_logs[
    purchase_logs["customer_id"].isin(
        purchase_logs[purchase_logs["product_id"] == selected_id]["customer_id"]
    )
]
top_cross_sell = (
    co_purchases[co_purchases["product_id"] != selected_id]
    .groupby("product_id").size()
    .nlargest(3)
    .index.tolist()
)
```

---

## Development Workflow

### Running the application

```bash
# Install dependencies (once requirements.txt exists)
pip install -r requirements.txt

# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run locally
streamlit run app.py
```

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic Claude API access |

Never commit API keys. The `.gitignore` already excludes `.env` and `.envrc`.

### Git branches

- `master` — stable/main branch
- `claude/...` — AI-assistant working branches (current: `claude/claude-md-mlwgsjov5p43w92s-kgBBr`)

---

## Naming Conventions

- All column names and JSON keys: `snake_case`
- IDs for master data (customers, products): `int`
- IDs for transactional data (logs, reviews): UUID strings
- Categorical values: lowercase English with underscores (e.g., `'dehydrated_oily'`, `'acne_trouble'`)

---

## Key Design Constraints

1. **Never pass the full database to the LLM.** The System always filters first; the Agent only sees the subset.
2. **Do not add a database until post-MVP.** JSON + Pandas in-memory is intentional for rapid iteration.
3. **Streamlit is the only frontend.** No React, no Flask. UI and backend live in `app.py`.
4. **Mock data is read-only** during MVP, except `customers.json` which gets new records appended on registration.
5. **Review text is Korean.** LLM prompts for summarization must handle Korean input and can output in either Korean or English depending on the UI language setting.

---

## Future Roadmap (post-MVP)

- Migrate from JSON to PostgreSQL; replace Pandas filters with SQL queries
- Add collaborative filtering for smarter cross-sell recommendations
- Implement search log storage in `logs.json` (currently only view/cart/purchase are logged)
- Deploy to Streamlit Cloud with secrets manager for `ANTHROPIC_API_KEY`
