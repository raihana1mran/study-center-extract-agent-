# NIOS Academic Study Centre Collection Agent

An autonomous multi-agent system that extracts all NIOS (National Institute of Open Schooling) **Academic** Study Centre data from India's SDMIS portal, stores it in PostgreSQL, and generates complete India-wide directories in DOCX, XLSX, and PDF format.

---

## Architecture

```
main.py (Orchestrator)
├── agents/
│   ├── browser_agent.py      ← Playwright headless Chromium
│   ├── extraction_agent.py   ← BeautifulSoup + Qwen3 Coder AI fallback
│   ├── validation_agent.py   ← Rule-based + GPT-OSS AI fallback
│   └── report_agent.py       ← DOCX + XLSX + PDF generation
├── db/
│   └── database.py           ← PostgreSQL via SQLAlchemy
└── utils/
    ├── logger.py             ← Loguru rotating logs
    ├── retry.py              ← Exponential backoff retry
    └── scheduler.py          ← APScheduler 30-day refresh
```

## Free OpenRouter Models Used

| Agent | Model | Purpose |
|---|---|---|
| Controller | `nvidia/nemotron-3-super-120b-a12b:free` | Orchestration |
| Browser | `google/gemma-4-26b-a4b-it:free` | Page navigation fallback |
| Extraction | `qwen/qwen3-coder:free` | HTML → structured data |
| Validation | `openai/gpt-oss-20b:free` | Field validation |
| Report | `google/gemma-4-31b-it:free` | Executive summary |

All models confirmed free (pricing: `"0"`) from OpenRouter API.

---

## Quick Start

### 1. Prerequisites
- Python 3.9+
- PostgreSQL running locally

### 2. Setup (one command)
```bash
python setup.py
```
This installs all packages, Playwright browser, creates `.env`, and initialises the DB.

### 3. Configure `.env`
```env
OPENROUTER_API_KEY=sk-or-v1-...   # Get free at https://openrouter.ai
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/nios_db
```

### 4. Run

```bash
# Test run (Delhi, 1 district only)
python main.py --test

# Full India-wide extraction
python main.py

# With 30-day auto-refresh
python main.py --schedule

# Reports only (from existing DB data)
python main.py --reports-only

# Single state
python main.py --state 9107       # Delhi
python main.py --state 9127       # Maharashtra
```

---

## Output Files

| File | Description |
|---|---|
| `reports/study_centres_india.docx` | Formatted Word document |
| `reports/study_centres_india.xlsx` | Multi-sheet Excel (one sheet/state) |
| `reports/study_centres_india.pdf` | Printable PDF directory |
| `logs/agent_YYYYMMDD_HHMMSS.log` | Full execution log |
| `logs/screenshots/` | Debug screenshots on errors |

## Document Structure

```
STATE (e.g., Maharashtra)
  └─ DISTRICT (e.g., Pune)
       ├─ AI Code     : 12345
       ├─ Study Centre: ABC Study Centre
       └─ Address     : 123 Main Road, Pune - 411001
```

---

## State Codes Reference

| State | Code | State | Code |
|---|---|---|---|
| Delhi | 9107 | Maharashtra | 9127 |
| Uttar Pradesh | 9109 | West Bengal | 9119 |
| Tamil Nadu | 9133 | Karnataka | 9129 |
| Rajasthan | 9108 | Andhra Pradesh | 9128 |
| Gujarat | 9124 | Madhya Pradesh | 9123 |

---

## Features

- ✅ **Academic only** — extracts only Academic category study centres
- ✅ **All 37 States/UTs** — complete India coverage including Ladakh
- ✅ **3-retry policy** — exponential backoff per district, continues on failure
- ✅ **Checkpoint/resume** — crashes don't restart from scratch
- ✅ **Deduplication** — UPSERT on `ai_code` prevents duplicate rows
- ✅ **Field validation** — flags missing AI Code, Name, District, State
- ✅ **Execution logs** — rotating logs with timestamps
- ✅ **Debug screenshots** — auto-captured on errors
- ✅ **30-day scheduler** — automatic refresh with PostgreSQL job persistence
- ✅ **Zero cost** — all OpenRouter models are free tier

---

## Database Schema

```sql
CREATE TABLE study_centres (
    id             SERIAL PRIMARY KEY,
    ai_code        VARCHAR(30) UNIQUE NOT NULL,
    name           TEXT NOT NULL,
    address        TEXT,
    district       VARCHAR(150),
    state          VARCHAR(150),
    category       VARCHAR(30) DEFAULT 'Academic',
    is_valid       BOOLEAN DEFAULT TRUE,
    missing_fields JSON,
    created_at     TIMESTAMP,
    updated_at     TIMESTAMP
);
```

---

## Source

Data sourced from: [sdmis.nios.ac.in](https://sdmis.nios.ac.in/registration/locate-study-center)
