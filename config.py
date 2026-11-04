"""API keys, limits, and settings."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
ASSETS_DIR = BASE_DIR / "assets"
PUBLIC_DIR = BASE_DIR / "public"
AUDIT_PDF_TEMPLATES_DIR = BASE_DIR / "audit-pdfs-templetes"
REPORTS_DIR = DATA_DIR / "reports"

load_dotenv(BASE_DIR / ".env")

# --- Branding / logos (prefer public/; fall back to assets/) ---
_GROWVA_PUBLIC = PUBLIC_DIR / "growvabusiness-logo.png"
_GROWVA_ASSETS = ASSETS_DIR / "growva_logo.png"
GROWVA_LOGO = _GROWVA_PUBLIC if _GROWVA_PUBLIC.exists() else _GROWVA_ASSETS

_PT_PUBLIC = PUBLIC_DIR / "ProcedureTracking-Logo-V3-Final.png"
_PT_ASSETS = ASSETS_DIR / "proceduretracking_logo.png"
PROCEDURETRACKING_LOGO = _PT_PUBLIC if _PT_PUBLIC.exists() else _PT_ASSETS

GROWVA_REVIEWS_AUDIT_TEMPLATE = (
    AUDIT_PDF_TEMPLATES_DIR / "Growva Business Google Reviews Audit Report.pdf"
)
GROWVA_SITE = os.getenv("GROWVA_SITE", "https://growvabusiness.app")

# --- API keys & SMTP ---
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "")
# When set, apify_scraper loads this JSON fixture instead of calling Apify
_APIFY_FIXTURE = os.getenv("APIFY_DRY_FIXTURE_PATH", "").strip()
APIFY_DRY_FIXTURE_PATH = Path(_APIFY_FIXTURE) if _APIFY_FIXTURE else None
if APIFY_DRY_FIXTURE_PATH and not APIFY_DRY_FIXTURE_PATH.is_absolute():
    APIFY_DRY_FIXTURE_PATH = BASE_DIR / APIFY_DRY_FIXTURE_PATH
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
IMAP_HOST = os.getenv("IMAP_HOST", "")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SENDER_NAME = os.getenv("SENDER_NAME", "Growva Business")
SENDER_FULL_NAME = os.getenv("SENDER_FULL_NAME", SENDER_NAME)
SENDER_EMAIL = os.getenv("SENDER_EMAIL", SMTP_USER)

# --- Campaign daily caps & sequence length ---
AU_DAILY_LIMIT = int(os.getenv("AU_DAILY_LIMIT", "15"))
PK_DAILY_LIMIT = int(os.getenv("PK_DAILY_LIMIT", "5"))
DELAY_BETWEEN_EMAILS_SEC = int(os.getenv("DELAY_BETWEEN_EMAILS_SEC", "90"))
AU_MAX_FOLLOW_UPS = 6
PK_MAX_FOLLOW_UPS = 5
MAX_FOLLOW_UPS = AU_MAX_FOLLOW_UPS  # legacy alias (prefer max_follow_ups_for)
SEND_HOUR_LOCAL = 9  # 09:00–09:59 local grace window for cron

# Sequence day offsets from Email 1 (calendar days; then shift to Mon–Thu)
SEQUENCE_OFFSETS = {
    1: 0,
    2: 3,
    3: 6,
    4: 9,
    5: 13,
    6: 17,
}

# --- Timezones ---
PAKISTAN_TZ = "Asia/Karachi"
AU_CITY_TIMEZONES = {
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth",
    "adelaide": "Australia/Adelaide",
    "hobart": "Australia/Hobart",
    "darwin": "Australia/Darwin",
    "canberra": "Australia/Sydney",
    "gold coast": "Australia/Brisbane",
    "newcastle": "Australia/Sydney",
}
DEFAULT_AU_TZ = "Australia/Sydney"

# --- Data files ---
AUSTRALIA_MANUAL_CSV = DATA_DIR / "australia_manual.csv"
PAKISTAN_SCHOOLS_CSV = DATA_DIR / "pakistan_schools_manual.csv"
SENT_HISTORY_CSV = DATA_DIR / "sent_history.csv"
LEAD_BACKLOG_CSV = DATA_DIR / "lead_backlog.csv"
APIFY_RAW_CSV = DATA_DIR / "apify_raw_leads.csv"

# --- Apify fallback cities ---
AUSTRALIA_FALLBACK_CITIES = [
    "Sydney",
    "Melbourne",
    "Brisbane",
    "Perth",
    "Adelaide",
]


def daily_limit_for(campaign_type: str) -> int:
    if (campaign_type or "").lower() == "pakistan":
        return PK_DAILY_LIMIT
    return AU_DAILY_LIMIT


def max_follow_ups_for(campaign_type: str, au_track: str = "") -> int:
    """Australia Growva track = 6; AU security-school track and Pakistan = 5."""
    campaign = (campaign_type or "").lower()
    track = (au_track or "").lower()
    if campaign == "pakistan" or track == "security":
        return PK_MAX_FOLLOW_UPS
    if campaign == "australia":
        return AU_MAX_FOLLOW_UPS
    return PK_MAX_FOLLOW_UPS
