"""
config.py — Central configuration for NIOS Study Centre Agent
All settings loaded from environment variables (.env file)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# ─── OpenRouter Free Models ─────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Model assignments (all confirmed free with pricing: "0")
MODELS = {
    # Controller / Orchestrator — powerful reasoning model
    "controller": "nvidia/nemotron-3-super-120b-a12b:free",

    # Browser Agent — Gemma 4, multimodal, great for page understanding
    "browser": "google/gemma-4-26b-a4b-it:free",

    # Extraction Agent — Qwen3 Coder, excellent structured data extraction
    "extraction": "qwen/qwen3-coder:free",

    # Validation Agent — GPT-OSS 20B, strong reasoning for field validation
    "validation": "openai/gpt-oss-20b:free",

    # Report Agent — Gemma 4 31B, good for text generation / summarization
    "report": "google/gemma-4-31b-it:free",
}

# ─── Database ───────────────────────────────────────────────────
DB_PATH = BASE_DIR / "db" / "nios.db"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{DB_PATH}"
)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ─── NIOS URLs ──────────────────────────────────────────────────
NIOS_BASE_URL = os.getenv("NIOS_BASE_URL", "https://sdmis.nios.ac.in")
NIOS_LOCATOR_URL = os.getenv(
    "NIOS_LOCATOR_URL",
    "https://sdmis.nios.ac.in/registration/locate-study-center"
)

# Category value for Academic only (as per user requirement)
CATEGORY_ACADEMIC = "1"
CATEGORY_NAME = "Academic"

# India country code on NIOS portal
COUNTRY_CODE_INDIA = "91"

# ─── All Indian States/UTs with their NIOS state codes ──────────
# Extracted directly from live NIOS portal HTML
INDIAN_STATES = [
    {"name": "Andaman and Nicobar Islands", "code": "9135"},
    {"name": "Andhra Pradesh",               "code": "9128"},
    {"name": "Arunachal Pradesh",            "code": "9112"},
    {"name": "Assam",                        "code": "9118"},
    {"name": "Bihar",                        "code": "9110"},
    {"name": "Chandigarh",                   "code": "9104"},
    {"name": "Chhattisgarh",                 "code": "9122"},
    {"name": "Dadra & Nagar Haveli",         "code": "9126"},
    {"name": "Daman & Diu",                  "code": "9125"},
    {"name": "Delhi",                        "code": "9107"},
    {"name": "Goa",                          "code": "9130"},
    {"name": "Gujarat",                      "code": "9124"},
    {"name": "Haryana",                      "code": "9106"},
    {"name": "Himachal Pradesh",             "code": "9102"},
    {"name": "Jammu and Kashmir",            "code": "9101"},
    {"name": "Jharkhand",                    "code": "9120"},
    {"name": "Karnataka",                    "code": "9129"},
    {"name": "Kerala",                       "code": "9132"},
    {"name": "Ladakh",                       "code": "9137"},
    {"name": "Lakshadweep",                  "code": "9131"},
    {"name": "Madhya Pradesh",               "code": "9123"},
    {"name": "Maharashtra",                  "code": "9127"},
    {"name": "Manipur",                      "code": "9114"},
    {"name": "Meghalaya",                    "code": "9117"},
    {"name": "Mizoram",                      "code": "9115"},
    {"name": "Nagaland",                     "code": "9113"},
    {"name": "Odisha",                       "code": "9121"},
    {"name": "Puducherry",                   "code": "9134"},
    {"name": "Punjab",                       "code": "9103"},
    {"name": "Rajasthan",                    "code": "9108"},
    {"name": "Sikkim",                       "code": "9111"},
    {"name": "Tamil Nadu",                   "code": "9133"},
    {"name": "Telangana",                    "code": "9136"},
    {"name": "Tripura",                      "code": "9116"},
    {"name": "Uttar Pradesh",               "code": "9109"},
    {"name": "Uttarakhand",                  "code": "9105"},
    {"name": "West Bengal",                  "code": "9119"},
]

# ─── Agent Behaviour ────────────────────────────────────────────
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "2"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
BROWSER_TIMEOUT_MS = 30_000   # 30 seconds per page action
FORM_TIMEOUT_MS = 15_000      # 15 seconds for form responses

# ─── Scheduler ──────────────────────────────────────────────────
REFRESH_DAYS = int(os.getenv("REFRESH_DAYS", "30"))

# ─── Output Paths ───────────────────────────────────────────────
REPORTS_DIR = BASE_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"
SCREENSHOTS_DIR = BASE_DIR / "logs" / "screenshots"

REPORTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)

DOCX_PATH = REPORTS_DIR / "study_centres_india.docx"
XLSX_PATH = REPORTS_DIR / "study_centres_india.xlsx"
PDF_PATH  = REPORTS_DIR / "study_centres_india.pdf"
JSON_PATH = REPORTS_DIR / "study_centres_india.json"
