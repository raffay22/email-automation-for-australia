"""Master scheduler & runner — dual campaign, cron-safe daily queue."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import config
import database
from generator.pdf_builder import (
    build_custom_audit_pdf,
    build_general_advisory_pdf,
    build_reviews_audit_pdf,
)
from generator.tech_detector import detect
from scraper.apify_scraper import scrape_australia_fallback
from scraper.lead_gate import assign_australia_track
from scraper.manual_loader import (
    load_australia,
    load_australia_raw,
    load_pakistan,
    pakistan_has_schools,
)
from sender.email_engine import (
    can_accept_send,
    dispatch_lead,
    is_send_window_open,
    is_step_due,
)
from sender.tracker import check_replies


def _lead_key(lead: dict[str, Any]) -> str:
    url = database.normalize_url(lead.get("url", ""))
    if url:
        return f"url:{url}"
    email = (lead.get("email") or "").strip().lower()
    if email:
        return f"email:{email}"
    return f"name:{database.normalize_name(lead.get('business_name', ''))}"


def _history_followups(campaign_type: str) -> list[dict[str, Any]]:
    """Rebuild mid-sequence leads from history (e.g. Apify-sourced)."""
    latest: dict[str, dict[str, str]] = {}
    for row in database.load_history():
        if (row.get("campaign_type") or "").lower() != campaign_type:
            continue
        key = database.normalize_url(row.get("url", "")) or (row.get("email") or "").lower()
        if not key:
            continue
        latest[key] = row

    leads: list[dict[str, Any]] = []
    for row in latest.values():
        try:
            step = int(row.get("email_step") or 0)
        except ValueError:
            step = 0
        stored_track = (row.get("au_track") or "").strip().lower()
        max_steps = config.max_follow_ups_for(campaign_type, au_track=stored_track)
        if step <= 0 or step >= max_steps:
            continue
        if database.is_stopped(url=row.get("url", ""), email=row.get("email", "")):
            continue
        lead: dict[str, Any] = {
            "business_name": row.get("business_name", ""),
            "email": row.get("email", ""),
            "url": row.get("url", ""),
            "city": row.get("city", ""),
            "campaign_type": campaign_type,
            "source": "history",
        }
        if campaign_type == "australia":
            if stored_track in {"growva", "security"}:
                lead["au_track"] = stored_track
            else:
                # Never default missing track to growva — re-gate (may skip schools)
                tagged = assign_australia_track(lead)
                if tagged is None:
                    continue
                lead = tagged
        leads.append(lead)
    return leads


def _apply_au_gate(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tag Growva vs security tracks; drop AU schools without PHP/legacy issues."""
    out: list[dict[str, Any]] = []
    for lead in leads:
        step = database.get_sequence_step(url=lead.get("url", ""), email=lead.get("email", ""))
        stored = (lead.get("au_track") or "").strip().lower()

        # Trust explicit stored track on follow-ups only
        if step > 0 and stored in {"growva", "security"}:
            out.append(lead)
            continue

        tagged = assign_australia_track(lead)
        if tagged is not None:
            out.append(tagged)
    return out


def gather_australia_leads(use_apify: bool = True) -> list[dict[str, Any]]:
    """
    Manual AU first, then local Apify backlog, then live Apify if still short.
    Excess scraped leads beyond today's remaining quota are saved to backlog.
    School gate applied before return.
    """
    manual_raw = load_australia_raw()
    manual = load_australia(skip_processed=True)
    followups = _history_followups("australia")

    merged: dict[str, dict[str, Any]] = {}
    for lead in followups + manual:
        merged[_lead_key(lead)] = lead

    remaining_cap = max(
        0,
        config.AU_DAILY_LIMIT - database.count_sends_today("australia"),
    )

    def _new_count() -> int:
        return sum(
            1
            for lead in merged.values()
            if database.get_sequence_step(url=lead.get("url", ""), email=lead.get("email", "")) == 0
        )

    backlog_leads = database.list_queued_backlog("australia")
    if backlog_leads:
        print(f"[main] Loaded {len(backlog_leads)} lead(s) from local Apify backlog")
    for lead in backlog_leads:
        if remaining_cap <= 0 or _new_count() >= remaining_cap:
            break
        key = _lead_key(lead)
        if key in merged:
            continue
        if database.is_already_processed(lead.get("url", ""), lead.get("business_name", "")):
            continue
        merged[key] = {**lead, "source": lead.get("source") or "backlog"}

    new_eligible_count = _new_count()
    need_apify = use_apify and (
        len(manual_raw) == 0 or (remaining_cap > 0 and new_eligible_count < remaining_cap)
    )
    if need_apify:
        needed = max(remaining_cap - new_eligible_count, 1) if remaining_cap else 0
        if needed > 0:
            print(f"[main] Australia Apify fallback (need ~{needed} new leads)")
            scraped = scrape_australia_fallback(needed=needed)
            today_slots = max(remaining_cap - _new_count(), 0)
            for_today: list[dict[str, Any]] = []
            for_backlog: list[dict[str, Any]] = []

            for lead in scraped:
                key = _lead_key(lead)
                if not key or key in merged:
                    continue
                if database.is_already_processed(lead.get("url", ""), lead.get("business_name", "")):
                    continue
                if len(for_today) < today_slots:
                    for_today.append(lead)
                    merged[key] = lead
                else:
                    for_backlog.append(lead)

            if for_backlog:
                database.enqueue_backlog(for_backlog, campaign_type="australia")
            print(
                f"[main] Apify: using {len(for_today)} today, "
                f"backlogged {len(for_backlog)} for later days"
            )

    gated = _apply_au_gate(list(merged.values()))
    print(f"[main] Australia after school gate: {len(gated)} lead(s)")
    return gated


def gather_pakistan_leads() -> list[dict[str, Any]]:
    """Manual only. Empty file => no sends."""
    if not pakistan_has_schools():
        print("[main] Pakistan manual CSV empty — skipping Pakistan campaign")
        return []

    manual = load_pakistan(skip_processed=True)
    followups = _history_followups("pakistan")
    merged: dict[str, dict[str, Any]] = {}
    for lead in followups + manual:
        merged[_lead_key(lead)] = lead
    return list(merged.values())


def _prepare_pdfs(
    lead: dict[str, Any],
    step: int,
    cache_general: dict[str, Path | None],
) -> tuple[Path | None, Path | None, Path | None]:
    """Returns (general_pdf, custom_tech_pdf, reviews_pdf). Fail-closed on AU track."""
    campaign = (lead.get("campaign_type") or "australia").lower()
    au_track = (lead.get("au_track") or "").strip().lower()

    general_pdf: Path | None = None
    custom_pdf: Path | None = None
    reviews_pdf: Path | None = None

    # Growva service businesses only — reviews PDF, never tech PDFs
    if campaign == "australia" and au_track == "growva":
        if step == 2:
            reviews_pdf = build_reviews_audit_pdf(lead)
        return None, None, reviews_pdf

    # AU security schools — tech PDFs only, never reviews
    if campaign == "australia" and au_track == "security":
        general_pdf = cache_general.get("australia")
        if general_pdf is None and step == 1:
            general_pdf = build_general_advisory_pdf("australia")
            cache_general["australia"] = general_pdf
        if step in {2, 5}:
            existing = database.get_custom_pdf_path(
                url=lead.get("url", ""), email=lead.get("email", "")
            )
            if existing and Path(existing).exists() and step == 5:
                custom_pdf = Path(existing)
            else:
                tech = lead.get("_tech_cache") or detect(lead.get("url") or "")
                custom_pdf = build_custom_audit_pdf(lead, tech, campaign="australia")
        return general_pdf, custom_pdf, None

    if campaign == "australia":
        # Missing/invalid track — do not build any AU PDF
        return None, None, None

    # Pakistan — tech PDFs
    general_pdf = cache_general.get(campaign)
    if general_pdf is None and step == 1:
        general_pdf = build_general_advisory_pdf(campaign)
        cache_general[campaign] = general_pdf

    if step in {2, 5}:
        existing = database.get_custom_pdf_path(url=lead.get("url", ""), email=lead.get("email", ""))
        if existing and Path(existing).exists() and step == 5:
            custom_pdf = Path(existing)
        else:
            tech = lead.get("_tech_cache") or detect(lead.get("url") or "")
            custom_pdf = build_custom_audit_pdf(lead, tech, campaign=campaign)
    return general_pdf, custom_pdf, reviews_pdf


def process_campaign(
    leads: list[dict[str, Any]],
    campaign_type: str,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    ignore_hour: bool = False,
) -> int:
    sent = 0
    cache_general: dict[str, Path | None] = {}

    for lead in leads:
        if not can_accept_send(campaign_type, sent, limit_override=limit):
            break

        url = lead.get("url", "")
        email = lead.get("email", "")
        if database.is_stopped(url=url, email=email):
            continue

        current = database.get_sequence_step(url=url, email=email)
        step = current + 1
        au_track = (lead.get("au_track") or "").strip().lower()
        if campaign_type == "australia" and au_track not in {"growva", "security"}:
            print(
                f"[main] Skip AU lead without explicit au_track: "
                f"{lead.get('business_name')} / {email}"
            )
            continue
        max_steps = config.max_follow_ups_for(campaign_type, au_track=au_track)
        if step > max_steps:
            continue

        if step == 1 and database.is_already_processed(url, lead.get("business_name", "")):
            continue

        if not is_send_window_open(lead, ignore_hour=ignore_hour):
            continue
        if not is_step_due(lead, step):
            continue

        if step >= 2 and database.is_stopped(url=url, email=email):
            continue

        general_pdf, custom_pdf, reviews_pdf = _prepare_pdfs(lead, step, cache_general)
        if dispatch_lead(
            lead,
            general_pdf=general_pdf,
            custom_pdf=custom_pdf,
            reviews_pdf=reviews_pdf,
            dry_run=dry_run,
            ignore_hour=ignore_hour,
        ):
            sent += 1
            if step == 1:
                database.remove_from_backlog([lead])
            track = lead.get("au_track") or campaign_type
            print(
                f"[main] Sent email_{step} → {email} ({track})"
                + (" [dry-run]" if dry_run else "")
            )

    return sent


def run(
    *,
    campaign: str = "all",
    limit: int | None = None,
    use_apify: bool = True,
    dry_run: bool = False,
    ignore_hour: bool = False,
) -> None:
    check_replies()

    total = 0
    if campaign in {"all", "australia"}:
        au_leads = gather_australia_leads(use_apify=use_apify)
        au_limit = limit if limit is not None else config.AU_DAILY_LIMIT
        n = process_campaign(
            au_leads,
            "australia",
            limit=au_limit,
            dry_run=dry_run,
            ignore_hour=ignore_hour,
        )
        total += n
        print(f"[main] Australia sent {n} (cap={au_limit})")

    if campaign in {"all", "pakistan"}:
        pk_leads = gather_pakistan_leads()
        pk_limit = limit if limit is not None else config.PK_DAILY_LIMIT
        n = process_campaign(
            pk_leads,
            "pakistan",
            limit=pk_limit,
            dry_run=dry_run,
            ignore_hour=ignore_hour,
        )
        total += n
        print(f"[main] Pakistan sent {n} (cap={pk_limit})")

    print(f"[main] Done. Total sends this run: {total}")


def main() -> None:
    parser = argparse.ArgumentParser(description="B2B outreach dual-campaign runner")
    parser.add_argument(
        "--campaign",
        choices=["all", "australia", "pakistan"],
        default="all",
        help="Which campaign queue to process",
    )
    parser.add_argument("--limit", type=int, default=None, help="Override per-campaign send cap")
    parser.add_argument(
        "--no-apify",
        action="store_true",
        help="Disable Australia Apify fallback",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions without SMTP send",
    )
    parser.add_argument(
        "--ignore-hour",
        action="store_true",
        help="Skip the 9 AM local hour check (still enforces Mon–Thu)",
    )
    parser.add_argument(
        "--check-replies-only",
        action="store_true",
        help="Only poll inbox for replies",
    )
    args = parser.parse_args()

    if args.check_replies_only:
        found = check_replies()
        print(f"[main] Marked {len(found)} replier(s) as stopped.")
        return

    run(
        campaign=args.campaign,
        limit=args.limit,
        use_apify=not args.no_apify,
        dry_run=args.dry_run,
        ignore_hour=args.ignore_hour,
    )


if __name__ == "__main__":
    main()
