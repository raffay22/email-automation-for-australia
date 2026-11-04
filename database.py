"""Duplicate check & tracking logic (CSV-backed)."""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import config

HISTORY_FIELDS = [
    "url",
    "business_name",
    "email",
    "city",
    "campaign_type",
    "au_track",
    "email_step",
    "sent_date",
    "status",
    "replied",
    "stopped",
    "custom_pdf_path",
]


def _ensure_history_file() -> Path:
    path = config.SENT_HISTORY_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
            writer.writeheader()
        return path

    # Migrate header if an older scaffold schema is present.
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []
        rows = list(reader)
    if list(existing_fields) != HISTORY_FIELDS:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow(_coerce_row(row))
    return path


def _coerce_row(row: dict[str, str]) -> dict[str, str]:
    """Map legacy scaffold columns onto the current schema."""
    return {
        "url": row.get("url") or row.get("website") or "",
        "business_name": row.get("business_name") or row.get("school_name") or "",
        "email": row.get("email") or "",
        "city": row.get("city") or "",
        "campaign_type": row.get("campaign_type") or row.get("country") or "",
        "au_track": (row.get("au_track") or "").strip().lower(),
        "email_step": row.get("email_step") or row.get("sequence_step") or "0",
        "sent_date": row.get("sent_date") or row.get("last_sent_at") or "",
        "status": row.get("status") or "",
        "replied": row.get("replied") or "false",
        "stopped": row.get("stopped") or "false",
        "custom_pdf_path": row.get("custom_pdf_path") or "",
    }


def load_history() -> list[dict[str, str]]:
    path = _ensure_history_file()
    with path.open(newline="", encoding="utf-8") as f:
        return [_coerce_row(row) for row in csv.DictReader(f)]


def normalize_url(url: str) -> str:
    raw = (url or "").strip().lower()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.netloc or "").removeprefix("www.")
    path = (parsed.path or "").rstrip("/")
    return f"{host}{path}"


def normalize_name(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def _truthy(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def is_already_processed(url: str, business_name: str) -> bool:
    """True if url OR business_name already appears in history."""
    n_url = normalize_url(url)
    n_name = normalize_name(business_name)
    if not n_url and not n_name:
        return False
    for row in load_history():
        if n_url and normalize_url(row.get("url", "")) == n_url:
            return True
        if n_name and normalize_name(row.get("business_name", "")) == n_name:
            return True
    return False


def get_lead_state(url: str = "", email: str = "") -> dict[str, str] | None:
    n_url = normalize_url(url)
    n_email = (email or "").strip().lower()
    for row in reversed(load_history()):
        if n_url and normalize_url(row.get("url", "")) == n_url:
            return row
        if n_email and (row.get("email") or "").strip().lower() == n_email:
            return row
    return None


def get_sequence_step(url: str = "", email: str = "") -> int:
    record = get_lead_state(url=url, email=email)
    if not record:
        return 0
    try:
        return int(record.get("email_step") or 0)
    except ValueError:
        return 0


def get_first_sent_date(url: str = "", email: str = "") -> date | None:
    """Earliest sent_date for this lead (Email 1 anchor)."""
    n_url = normalize_url(url)
    n_email = (email or "").strip().lower()
    earliest: date | None = None
    for row in load_history():
        match = False
        if n_url and normalize_url(row.get("url", "")) == n_url:
            match = True
        elif n_email and (row.get("email") or "").strip().lower() == n_email:
            match = True
        if not match:
            continue
        raw = (row.get("sent_date") or "").strip()
        if not raw:
            continue
        parsed = _parse_date(raw)
        if parsed and (earliest is None or parsed < earliest):
            earliest = parsed
    return earliest


def get_custom_pdf_path(url: str = "", email: str = "") -> str:
    record = get_lead_state(url=url, email=email)
    return (record or {}).get("custom_pdf_path") or ""


def is_stopped(url: str = "", email: str = "") -> bool:
    record = get_lead_state(url=url, email=email)
    if not record:
        return False
    return _truthy(record.get("stopped", "")) or _truthy(record.get("replied", ""))


def count_sends_today(campaign_type: str, today: date | None = None) -> int:
    today = today or datetime.now(timezone.utc).date()
    campaign = (campaign_type or "").strip().lower()
    count = 0
    for row in load_history():
        if (row.get("campaign_type") or "").strip().lower() != campaign:
            continue
        sent = _parse_date(row.get("sent_date") or "")
        if sent == today:
            count += 1
    return count


def record_send(
    *,
    url: str,
    business_name: str,
    email: str,
    city: str,
    campaign_type: str,
    email_step: int,
    status: str = "sent",
    custom_pdf_path: str = "",
    au_track: str = "",
) -> None:
    path = _ensure_history_file()
    prior = get_lead_state(url=url, email=email)
    pdf_path = custom_pdf_path or (prior.get("custom_pdf_path") if prior else "") or ""
    track = (au_track or (prior.get("au_track") if prior else "") or "").strip().lower()
    row: dict[str, Any] = {
        "url": (url or "").strip(),
        "business_name": (business_name or "").strip(),
        "email": (email or "").strip().lower(),
        "city": (city or "").strip(),
        "campaign_type": (campaign_type or "").strip().lower(),
        "au_track": track,
        "email_step": str(email_step),
        "sent_date": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "replied": "false",
        "stopped": "false",
        "custom_pdf_path": pdf_path,
    }
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        writer.writerow(row)


def mark_replied_by_url(url: str = "", email: str = "") -> None:
    _rewrite_flags(url=url, email=email, replied="true", stopped="true")


def mark_stopped(url: str = "", email: str = "") -> None:
    _rewrite_flags(url=url, email=email, stopped="true")


def _rewrite_flags(url: str = "", email: str = "", **flags: str) -> None:
    n_url = normalize_url(url)
    n_email = (email or "").strip().lower()
    path = _ensure_history_file()
    rows = load_history()
    changed = False
    for row in rows:
        match = False
        if n_url and normalize_url(row.get("url", "")) == n_url:
            match = True
        elif n_email and (row.get("email") or "").strip().lower() == n_email:
            match = True
        if match:
            row.update(flags)
            changed = True
    if not changed:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        if "T" in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def active_outreach_emails() -> set[str]:
    emails: set[str] = set()
    for row in load_history():
        if _truthy(row.get("stopped", "")) or _truthy(row.get("replied", "")):
            continue
        email = (row.get("email") or "").strip().lower()
        if email:
            emails.add(email)
    return emails


def email_to_url_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in load_history():
        email = (row.get("email") or "").strip().lower()
        url = (row.get("url") or "").strip()
        if email and url:
            mapping[email] = url
    return mapping


# ---------------------------------------------------------------------------
# Apify / overflow lead backlog (queued for future outreach days)
# ---------------------------------------------------------------------------

BACKLOG_FIELDS = [
    "url",
    "business_name",
    "email",
    "city",
    "campaign_type",
    "source",
    "queued_at",
    "status",
]


def _ensure_backlog_file() -> Path:
    path = config.LEAD_BACKLOG_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=BACKLOG_FIELDS).writeheader()
    return path


def load_backlog(campaign_type: str | None = None) -> list[dict[str, str]]:
    path = _ensure_backlog_file()
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if campaign_type:
        camp = campaign_type.strip().lower()
        rows = [r for r in rows if (r.get("campaign_type") or "").strip().lower() == camp]
    return rows


def _write_backlog(rows: list[dict[str, str]]) -> None:
    path = _ensure_backlog_file()
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BACKLOG_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in BACKLOG_FIELDS})


def _backlog_key(row: dict[str, Any]) -> str:
    n_url = normalize_url(row.get("url", ""))
    if n_url:
        return f"url:{n_url}"
    n_name = normalize_name(row.get("business_name", ""))
    if n_name:
        return f"name:{n_name}"
    email = (row.get("email") or "").strip().lower()
    return f"email:{email}" if email else ""


def enqueue_backlog(leads: list[dict[str, Any]], campaign_type: str = "australia") -> int:
    """
    Append new leads to the backlog queue. Skips duplicates already in backlog
    or already processed in sent history. Returns count newly queued.
    """
    if not leads:
        return 0

    existing = load_backlog()
    existing_keys = {_backlog_key(r) for r in existing if _backlog_key(r)}
    added = 0
    now = datetime.now(timezone.utc).isoformat()

    for lead in leads:
        camp = (lead.get("campaign_type") or campaign_type or "australia").strip().lower()
        url = (lead.get("url") or "").strip()
        name = (lead.get("business_name") or "").strip()
        if is_already_processed(url, name):
            continue
        key = _backlog_key(lead)
        if not key or key in existing_keys:
            continue
        existing.append(
            {
                "url": url,
                "business_name": name,
                "email": (lead.get("email") or "").strip().lower(),
                "city": (lead.get("city") or "").strip(),
                "campaign_type": camp,
                "source": (lead.get("source") or "apify").strip(),
                "queued_at": now,
                "status": "queued",
            }
        )
        existing_keys.add(key)
        added += 1

    if added:
        _write_backlog(existing)
        print(f"[backlog] Queued {added} excess lead(s) for later outreach")
    return added


def list_queued_backlog(campaign_type: str = "australia") -> list[dict[str, Any]]:
    """
    Return queued backlog leads for a campaign, dropping any already processed.
    Purges stale processed rows from the CSV.
    """
    all_rows = load_backlog()
    camp = campaign_type.strip().lower()
    kept: list[dict[str, str]] = []
    eligible: list[dict[str, Any]] = []

    for row in all_rows:
        row_camp = (row.get("campaign_type") or "").strip().lower()
        url = row.get("url", "")
        name = row.get("business_name", "")
        if is_already_processed(url, name):
            # Drop from backlog once outreach has started / completed
            continue
        if (row.get("status") or "queued").strip().lower() != "queued":
            continue
        kept.append(row)
        if row_camp == camp:
            eligible.append(
                {
                    "business_name": name,
                    "email": (row.get("email") or "").strip().lower(),
                    "url": url,
                    "city": row.get("city", ""),
                    "campaign_type": row_camp or camp,
                    "source": row.get("source") or "backlog",
                }
            )

    if len(kept) != len(all_rows):
        _write_backlog(kept)
    return eligible


def remove_from_backlog(leads: list[dict[str, Any]]) -> int:
    """Remove matching leads from backlog (e.g. after successful first send)."""
    if not leads:
        return 0
    remove_keys = {_backlog_key(lead) for lead in leads if _backlog_key(lead)}
    if not remove_keys:
        return 0
    rows = load_backlog()
    kept = [r for r in rows if _backlog_key(r) not in remove_keys]
    removed = len(rows) - len(kept)
    if removed:
        _write_backlog(kept)
    return removed


# ---------------------------------------------------------------------------
# Raw Apify archive (WhatsApp / Instagram / manual follow-up later)
# ---------------------------------------------------------------------------

APIFY_RAW_FIELDS = [
    "business_name",
    "phone",
    "rating",
    "review_count",
    "maps_url",
    "instagram",
    "facebook",
    "website",
    "email",
    "city",
    "category",
    "scraped_at",
]


def _ensure_apify_raw_file() -> Path:
    path = config.APIFY_RAW_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=APIFY_RAW_FIELDS).writeheader()
    return path


def _raw_dedupe_key(row: dict[str, str]) -> str:
    maps = (row.get("maps_url") or "").strip().lower()
    if maps:
        return f"maps:{maps}"
    url = normalize_url(row.get("website") or "")
    name = normalize_name(row.get("business_name") or "")
    return f"{url}|{name}"


def append_apify_raw(item: dict[str, Any], city: str = "") -> bool:
    """
    Persist one raw Apify place record. Returns True if a new row was written.
    Dedupes on maps_url or website+name.
    """
    path = _ensure_apify_raw_file()
    with path.open(newline="", encoding="utf-8") as f:
        existing = list(csv.DictReader(f))
    existing_keys = {_raw_dedupe_key(r) for r in existing}

    def _pick(*keys: str) -> str:
        for key in keys:
            val = item.get(key)
            if val is None:
                continue
            if isinstance(val, list):
                for entry in val:
                    text = str(entry or "").strip()
                    if text:
                        return text
                continue
            text = str(val).strip()
            if text:
                return text
        return ""

    socials = item.get("socials") or item.get("socialMedia") or {}
    if not isinstance(socials, dict):
        socials = {}

    row = {
        "business_name": _pick("title", "name", "business_name"),
        "phone": _pick("phone", "phoneNumber", "telephone"),
        "rating": _pick("rating", "totalScore", "stars"),
        "review_count": _pick("review_count", "reviewsCount", "reviews", "totalReviews"),
        "maps_url": _pick("maps_url", "url", "googleMapsUrl", "placeUrl"),
        "instagram": _pick("instagram") or str(socials.get("instagram") or "").strip(),
        "facebook": _pick("facebook") or str(socials.get("facebook") or "").strip(),
        "website": _pick("website", "websiteUrl"),
        "email": _pick("email", "emails", "mail").lower(),
        "city": city or _pick("city", "addressCity"),
        "category": _pick("category", "categoryName", "type"),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    key = _raw_dedupe_key(row)
    if not key or key == "|" or key in existing_keys:
        return False
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=APIFY_RAW_FIELDS)
        writer.writerow(row)
    return True
