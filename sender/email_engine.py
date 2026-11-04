"""SMTP dispatcher with timezone & Mon–Thu business-day rules."""

from __future__ import annotations

import smtplib
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import config
import database


def is_business_day(d: date) -> bool:
    """True only for Monday–Thursday."""
    return d.weekday() <= 3  # Mon=0 … Thu=3


def next_business_day(d: date) -> date:
    """If d is Fri–Sun, advance to the following Monday; else return d."""
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def local_send_timezone(lead: dict[str, Any]) -> str:
    campaign = (lead.get("campaign_type") or "").lower()
    if campaign == "pakistan":
        return config.PAKISTAN_TZ
    city = (lead.get("city") or "").strip().lower()
    return config.AU_CITY_TIMEZONES.get(city, config.DEFAULT_AU_TZ)


def local_now(lead: dict[str, Any]) -> datetime:
    return datetime.now(ZoneInfo(local_send_timezone(lead)))


def is_send_window_open(lead: dict[str, Any], *, ignore_hour: bool = False) -> bool:
    """Mon–Thu in lead's local TZ; hour must be 9 (09:00–09:59) unless ignore_hour."""
    now = local_now(lead)
    if not is_business_day(now.date()):
        return False
    if ignore_hour:
        return True
    return now.hour == config.SEND_HOUR_LOCAL


def scheduled_send_date(first_sent: date | None, step: int) -> date | None:
    """Calendar due date for `step`, shifted to the next Mon–Thu if needed."""
    if step <= 1:
        return None
    if first_sent is None:
        return None
    offset = config.SEQUENCE_OFFSETS.get(step, 0)
    raw = first_sent + timedelta(days=offset)
    return next_business_day(raw)


def is_step_due(lead: dict[str, Any], step: int) -> bool:
    """Whether the next sequence step is due on the lead's local calendar today."""
    today = local_now(lead).date()
    if step <= 1:
        return is_business_day(today)

    first = database.get_first_sent_date(url=lead.get("url", ""), email=lead.get("email", ""))
    due = scheduled_send_date(first, step)
    if due is None:
        return False
    return today >= due and is_business_day(today)


class TrackRoutingError(ValueError):
    """Australia lead missing or invalid au_track."""


def _au_track(lead: dict[str, Any]) -> str | None:
    from scraper.lead_gate import require_australia_track

    return require_australia_track(lead)


def _template_path(step: int, lead: dict[str, Any]) -> Path:
    """Fail-closed: Growva templates only for au_track=growva; security never gets au_email_*."""
    campaign = (lead.get("campaign_type") or "").lower()

    if campaign == "australia":
        track = _au_track(lead)
        if track is None:
            raise TrackRoutingError(
                f"Missing/invalid au_track for Australia lead: {lead.get('business_name')}"
            )
        if track == "growva":
            path = config.TEMPLATES_DIR / f"au_email_{step}.txt"
            if not path.exists():
                raise TrackRoutingError(f"Missing Growva template: {path.name}")
            return path
        # security → tech templates only
        if step == 4:
            path = config.TEMPLATES_DIR / "email_4_australia.txt"
            if path.exists():
                return path
        return config.TEMPLATES_DIR / f"email_{step}.txt"

    # Pakistan — existing 5-step templates
    if step == 4:
        path = config.TEMPLATES_DIR / f"email_4_{campaign}.txt"
        if path.exists():
            return path
    return config.TEMPLATES_DIR / f"email_{step}.txt"


def load_template(step: int, lead: dict[str, Any]) -> tuple[str, str]:
    """Load campaign/track template and substitute placeholders."""
    path = _template_path(step, lead)
    raw = path.read_text(encoding="utf-8")
    campaign = (lead.get("campaign_type") or "").lower()
    mapping = {
        "{business_name}": lead.get("business_name") or "there",
        "{{business_name}}": lead.get("business_name") or "there",
        "{school_name}": lead.get("business_name") or "there",
        "{{school_name}}": lead.get("business_name") or "there",
        "{city}": lead.get("city") or "",
        "{{city}}": lead.get("city") or "",
        "{url}": lead.get("url") or "",
        "{{url}}": lead.get("url") or "",
        "{website}": lead.get("url") or "",
        "{{website}}": lead.get("url") or "",
        "{sender_name}": config.SENDER_NAME,
        "{{sender_name}}": config.SENDER_NAME,
        "{sender_full_name}": config.SENDER_FULL_NAME,
        "{sender_email}": config.SENDER_EMAIL or config.SMTP_USER,
        "{rating}": str(lead.get("rating") or "n/a"),
        "{review_count}": str(lead.get("review_count") or "0"),
        "{growva_site}": config.GROWVA_SITE,
        "{campaign}": campaign,
    }
    for key, value in mapping.items():
        raw = raw.replace(key, str(value))

    lines = raw.splitlines()
    subject = "Follow-up"
    body_start = 0
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        body_start = 1
        if body_start < len(lines) and not lines[body_start].strip():
            body_start += 1
    body = "\n".join(lines[body_start:]).strip()
    return subject, body


def send_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    attachment: Path | None = None,
    dry_run: bool = False,
) -> bool:
    if dry_run:
        print(f"[smtp:dry-run] To={to_email} Subject={subject} Attachment={attachment}")
        return True

    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        print("[smtp] Missing SMTP_USER / SMTP_PASSWORD")
        return False
    if not to_email:
        print("[smtp] Missing recipient email")
        return False

    msg = EmailMessage()
    msg["From"] = f"{config.SENDER_NAME} <{config.SENDER_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    if attachment and attachment.exists():
        data = attachment.read_bytes()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="pdf",
            filename=attachment.name,
        )

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.send_message(msg)
    return True


def resolve_attachment(
    step: int,
    lead: dict[str, Any],
    *,
    general_pdf: Path | None = None,
    custom_pdf: Path | None = None,
    reviews_pdf: Path | None = None,
) -> Path | None:
    """
    Fail-closed attachment matrix:
      Growva AU (au_track=growva only): E2 reviews PDF; never tech PDFs
      Security AU (au_track=security only): E1 general; E2/E5 custom tech; never reviews PDF
      Pakistan: E1 general; E2/E5 custom tech
    """
    campaign = (lead.get("campaign_type") or "").lower()

    if campaign == "australia":
        track = _au_track(lead)
        if track == "growva":
            return reviews_pdf if step == 2 else None
        if track == "security":
            if step == 1:
                return general_pdf
            if step in {2, 5}:
                return custom_pdf
            return None
        raise TrackRoutingError(
            f"Cannot resolve attachment without au_track: {lead.get('business_name')}"
        )

    # Pakistan
    if step == 1:
        return general_pdf
    if step in {2, 5}:
        return custom_pdf
    return None


def can_accept_send(campaign_type: str, sent_this_run: int, limit_override: int | None = None) -> bool:
    cap = limit_override if limit_override is not None else config.daily_limit_for(campaign_type)
    already = database.count_sends_today(campaign_type)
    return (already + sent_this_run) < cap


def dispatch_lead(
    lead: dict[str, Any],
    *,
    general_pdf: Path | None = None,
    custom_pdf: Path | None = None,
    reviews_pdf: Path | None = None,
    dry_run: bool = False,
    ignore_hour: bool = False,
) -> bool:
    """Send the next due sequence step for a lead if scheduling + caps allow."""
    email = (lead.get("email") or "").strip().lower()
    url = (lead.get("url") or "").strip()
    campaign = (lead.get("campaign_type") or "").strip().lower()
    au_track = _au_track(lead) if campaign == "australia" else ""

    if not email:
        return False
    if campaign == "australia" and au_track is None:
        print(
            f"[smtp] Refusing AU send — missing au_track "
            f"(must be growva|security): {lead.get('business_name')} / {email}"
        )
        return False
    if database.is_stopped(url=url, email=email):
        return False
    if not is_send_window_open(lead, ignore_hour=ignore_hour):
        print(f"[smtp] Outside send window ({local_send_timezone(lead)}): {email}")
        return False

    current = database.get_sequence_step(url=url, email=email)
    step = current + 1
    max_steps = config.max_follow_ups_for(campaign, au_track=au_track or "")
    if step > max_steps:
        return False

    if step == 1 and database.is_already_processed(url, lead.get("business_name", "")):
        print(f"[smtp] Duplicate lead skipped: {lead.get('business_name')} / {url}")
        return False

    if step >= 2 and database.is_stopped(url=url, email=email):
        return False

    if not is_step_due(lead, step):
        return False

    try:
        subject, body = load_template(step, lead)
        attachment = resolve_attachment(
            step,
            lead,
            general_pdf=general_pdf,
            custom_pdf=custom_pdf,
            reviews_pdf=reviews_pdf,
        )
    except TrackRoutingError as exc:
        print(f"[smtp] Track routing error: {exc}")
        return False

    # Safety nets: track/attachment mismatch must never send
    if campaign == "australia" and au_track == "security" and reviews_pdf and attachment == reviews_pdf:
        print("[smtp] Blocked reviews PDF on security track")
        return False
    if campaign == "australia" and au_track == "growva":
        if custom_pdf and attachment == custom_pdf:
            print("[smtp] Blocked tech custom PDF on growva track")
            return False
        if general_pdf and attachment == general_pdf:
            print("[smtp] Blocked tech general PDF on growva track")
            return False

    ok = send_email(
        to_email=email,
        subject=subject,
        body=body,
        attachment=attachment,
        dry_run=dry_run,
    )
    if ok:
        database.record_send(
            url=url,
            business_name=lead.get("business_name", ""),
            email=email,
            city=lead.get("city", ""),
            campaign_type=campaign,
            email_step=step,
            status="sent" if not dry_run else "dry_run",
            custom_pdf_path=str(custom_pdf or reviews_pdf or ""),
            au_track=au_track or "",
        )
        if not dry_run:
            time.sleep(config.DELAY_BETWEEN_EMAILS_SEC)
    return ok
