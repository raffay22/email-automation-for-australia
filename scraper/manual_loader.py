"""Reads manual lists (Australia & Pakistan)."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import config
import database

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _first(*values: str | None) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_lead(row: dict[str, str | None], campaign_type: str, row_num: int) -> dict[str, Any] | None:
    business_name = _first(
        row.get("business_name"),
        row.get("school_name"),
        row.get("name"),
    )
    email = _first(row.get("email")).lower()
    url = _first(row.get("url"), row.get("website"))
    city = _first(row.get("city"))

    if not email and not url:
        print(f"[manual] Skip row {row_num}: missing both email and url")
        return None
    if email and not EMAIL_RE.match(email):
        print(f"[manual] Skip row {row_num}: invalid email '{email}'")
        return None
    if not business_name:
        print(f"[manual] Skip row {row_num}: missing business_name/school_name")
        return None

    return {
        "business_name": business_name,
        "email": email,
        "url": url,
        "city": city,
        "campaign_type": campaign_type,
        "source": "manual",
    }


def _read_csv(path: Path, campaign_type: str) -> list[dict[str, Any]]:
    if not path.exists():
        print(f"[manual] File not found: {path}")
        return []

    leads: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            print(f"[manual] Empty or headerless CSV: {path}")
            return []
        for idx, row in enumerate(reader, start=2):
            lead = _normalize_lead(row, campaign_type=campaign_type, row_num=idx)
            if lead:
                leads.append(lead)
    return leads


def _is_eligible(lead: dict[str, Any]) -> bool:
    """New leads must pass dedupe; mid-sequence follow-ups stay eligible until step 5 / stop."""
    url = lead.get("url", "")
    email = lead.get("email", "")
    name = lead.get("business_name", "")
    if database.is_stopped(url=url, email=email):
        return False
    step = database.get_sequence_step(url=url, email=email)
    if step >= config.MAX_FOLLOW_UPS:
        return False
    if step > 0:
        return True
    if database.is_already_processed(url, name):
        print(f"[manual] Dedupe skip: {name} / {url}")
        return False
    return True


def load_australia(skip_processed: bool = True) -> list[dict[str, Any]]:
    leads = _read_csv(config.AUSTRALIA_MANUAL_CSV, campaign_type="australia")
    if not skip_processed:
        return leads
    return [lead for lead in leads if _is_eligible(lead)]


def load_pakistan(skip_processed: bool = True) -> list[dict[str, Any]]:
    """Pakistan uses ONLY this manual file. Empty file => no sends."""
    leads = _read_csv(config.PAKISTAN_SCHOOLS_CSV, campaign_type="pakistan")
    if not skip_processed:
        return leads
    return [lead for lead in leads if _is_eligible(lead)]


def load_australia_raw() -> list[dict[str, Any]]:
    """Unfiltered AU rows (used to decide Apify fallback)."""
    return _read_csv(config.AUSTRALIA_MANUAL_CSV, campaign_type="australia")


def load_pakistan_raw() -> list[dict[str, Any]]:
    """Unfiltered PK rows (empty => campaign must not send)."""
    return _read_csv(config.PAKISTAN_SCHOOLS_CSV, campaign_type="pakistan")


def pakistan_has_schools() -> bool:
    """Explicit empty-file contract for the Pakistan campaign."""
    return len(load_pakistan_raw()) > 0
