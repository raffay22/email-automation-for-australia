"""Dynamic ReportLab PDF generator with campaign logo logic."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import config

TOTAL_PAGES = 2


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or "report"))
    return cleaned[:60] or "report"


def _normalize_campaign(campaign: str | None) -> str:
    value = (campaign or "").strip().lower()
    if value in {"pakistan", "pk"}:
        return "pakistan"
    return "australia"


def _logo_specs(campaign: str) -> list[tuple[Path, str]]:
    """
    Core Rule 5 logo rule:
      australia → Growva only (never ProcedureTracking)
      pakistan  → Growva + ProcedureTracking
    """
    logos: list[tuple[Path, str]] = [(config.GROWVA_LOGO, "Growva Business")]
    if campaign == "pakistan":
        logos.append((config.PROCEDURETRACKING_LOGO, "ProcedureTracking"))
    return logos


def _draw_logos(c: Any, campaign: str, page_width: float, page_height: float) -> float:
    """Draw campaign logos; return y cursor below the header band."""
    from reportlab.lib.units import mm

    campaign = _normalize_campaign(campaign)
    y_top = page_height - 18 * mm
    x = 18 * mm
    logo_h = 14 * mm
    logo_w = 38 * mm

    drew_any = False
    for path, label in _logo_specs(campaign):
        if path.exists():
            try:
                c.drawImage(
                    str(path),
                    x,
                    y_top - logo_h,
                    width=logo_w,
                    height=logo_h,
                    preserveAspectRatio=True,
                    mask="auto",
                )
                x += logo_w + 6 * mm
                drew_any = True
                continue
            except Exception:
                pass
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x, y_top - 8 * mm, label)
        x += 45 * mm
        drew_any = True

    if not drew_any:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(18 * mm, y_top - 8 * mm, "Growva Business")

    rule_y = y_top - logo_h - 4 * mm
    c.setStrokeColorRGB(0.15, 0.25, 0.45)
    c.setLineWidth(1.2)
    c.line(18 * mm, rule_y, page_width - 18 * mm, rule_y)
    return rule_y - 10 * mm


def _footer(c: Any, page_width: float, page_num: int, total: int = TOTAL_PAGES) -> None:
    from reportlab.lib.units import mm

    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(18 * mm, 12 * mm, "Confidential — Website Technology Advisory")
    c.drawRightString(page_width - 18 * mm, 12 * mm, f"Page {page_num} of {total}")
    c.setFillColorRGB(0, 0, 0)


def _branding_line(campaign: str) -> str:
    if _normalize_campaign(campaign) == "pakistan":
        return "Growva Business + ProcedureTracking"
    return "Growva Business only"


def build_general_advisory_pdf(
    campaign: str,
    output_dir: Path | None = None,
) -> Path | None:
    """Email 1 attachment: general security/advisory PDF (exactly 2 pages)."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except ImportError:
        print("[pdf] Install reportlab to enable PDF generation.")
        return None

    campaign = _normalize_campaign(campaign)
    output_dir = output_dir or config.REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"general_advisory_{campaign}.pdf"

    c = canvas.Canvas(str(out_path), pagesize=A4)
    width, height = A4
    pages = 0

    # --- Page 1 ---
    y = _draw_logos(c, campaign, width, height)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(18 * mm, y, "Website Security & Technology Advisory")
    y -= 10 * mm
    c.setFont("Helvetica", 11)
    intro = [
        "This briefing outlines common risks we observe across school and SMB websites,",
        "and practical steps to harden hosting, CMS, and PHP stacks before an incident.",
        "",
        "Key themes covered in this advisory:",
    ]
    for line in intro:
        c.drawString(18 * mm, y, line)
        y -= 6 * mm

    bullets = [
        "1. Outdated server software and exposed version banners",
        "2. Unsupported PHP runtimes and missing security patches",
        "3. CMS plugins/themes left unmaintained after enrolment peaks",
        "4. Missing HTTPS redirects, weak TLS, or mixed content",
        "5. Backup gaps and slow recovery after defacement or ransomware",
    ]
    y -= 2 * mm
    for line in bullets:
        c.drawString(22 * mm, y, line)
        y -= 7 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(18 * mm, y, "Why this matters now")
    y -= 7 * mm
    c.setFont("Helvetica", 10)
    paras = [
        "Public school and business sites are high-visibility targets. Attackers scan for",
        "known CMS and PHP CVEs continuously. A short, structured review often reveals",
        "low-effort fixes that reduce exposure without a full rebuild.",
        "",
        "Use this document as a checklist with your IT provider or hosting partner.",
    ]
    for line in paras:
        c.drawString(18 * mm, y, line)
        y -= 5.5 * mm

    _footer(c, width, 1)
    pages += 1
    c.showPage()

    # --- Page 2 ---
    y = _draw_logos(c, campaign, width, height)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(18 * mm, y, "Recommended next steps")
    y -= 10 * mm
    steps = [
        "Inventory: confirm CMS, PHP version, hosting provider, and who owns DNS.",
        "Patch: apply CMS core/plugin updates; retire abandoned extensions.",
        "Harden: disable directory listing, restrict admin paths, enforce HTTPS.",
        "Monitor: enable uptime + file-change alerts; schedule monthly backups.",
        "Review: request a tailored audit PDF for your live domain (follow-up email).",
    ]
    for i, line in enumerate(steps, start=1):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(18 * mm, y, f"Step {i}")
        y -= 5 * mm
        c.setFont("Helvetica", 10)
        c.drawString(22 * mm, y, line)
        y -= 9 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(
        18 * mm,
        y,
        f"Prepared by {_branding_line(campaign)}. Reply to the outreach email for a custom audit.",
    )
    _footer(c, width, 2)
    pages += 1
    c.save()

    if pages != TOTAL_PAGES:
        print(f"[pdf] Warning: expected {TOTAL_PAGES} pages, wrote {pages}")
    return out_path


def build_custom_audit_pdf(
    lead: dict[str, Any],
    tech: dict[str, Any],
    campaign: str | None = None,
    output_dir: Path | None = None,
) -> Path | None:
    """Email 2 & 5 attachment: custom 2-page executive audit for the lead."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except ImportError:
        print("[pdf] Install reportlab to enable PDF generation.")
        return None

    campaign = _normalize_campaign(campaign or lead.get("campaign_type"))
    output_dir = output_dir or config.REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # Core Rule 5 injected variables
    business_name = str(lead.get("business_name") or "Your Organisation")
    url = str(tech.get("url") or lead.get("url") or "")
    server_type = str(tech.get("server_type") or tech.get("server") or "Not detected")
    php_version = str(tech.get("php_version") or "Not detected")
    cms = str(
        tech.get("cms")
        or (", ".join(tech.get("cms_hints") or []) if tech.get("cms_hints") else "Not detected")
    )

    variables = {
        "business_name": business_name,
        "server_type": server_type,
        "php_version": php_version,
        "url": url,
    }

    out_path = output_dir / f"{_safe_filename(business_name)}_custom_audit.pdf"
    c = canvas.Canvas(str(out_path), pagesize=A4)
    width, height = A4
    pages = 0

    # --- Page 1: Executive summary ---
    y = _draw_logos(c, campaign, width, height)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(18 * mm, y, "Executive Website Audit Report")
    y -= 9 * mm
    c.setFont("Helvetica", 11)
    c.drawString(18 * mm, y, f"Prepared for: {business_name}")
    y -= 6 * mm
    c.drawString(18 * mm, y, f"Target URL: {url}")
    y -= 6 * mm
    c.drawString(18 * mm, y, f"City: {lead.get('city') or 'n/a'}  |  Campaign: {campaign.title()}")
    y -= 12 * mm

    c.setFont("Helvetica-Bold", 13)
    c.drawString(18 * mm, y, "Live technology snapshot")
    y -= 8 * mm

    box_top = y + 4 * mm
    box_height = 42 * mm
    c.setStrokeColorRGB(0.15, 0.25, 0.45)
    c.setFillColorRGB(0.95, 0.96, 0.98)
    c.rect(18 * mm, box_top - box_height, width - 36 * mm, box_height, fill=1, stroke=1)
    c.setFillColorRGB(0, 0, 0)

    rows = [
        ("Business name", business_name),
        ("URL", url or "n/a"),
        ("Server type", server_type),
        ("PHP version", php_version),
        ("CMS", cms),
        ("HTTP status", str(tech.get("status_code") or "n/a")),
        ("Reachable", "Yes" if tech.get("reachable") else "No"),
    ]
    ty = box_top - 7 * mm
    for label, value in rows:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(22 * mm, ty, f"{label}:")
        c.setFont("Helvetica", 9)
        c.drawString(55 * mm, ty, str(value)[:85])
        ty -= 5.2 * mm

    y = box_top - box_height - 10 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(18 * mm, y, "Findings overview")
    y -= 7 * mm
    c.setFont("Helvetica", 10)
    findings = [
        f"• Server banner reports: {server_type}",
        f"• PHP signal: {php_version}",
        f"• CMS indicators: {cms}",
        "• Version disclosure in headers can aid automated scanners.",
        "• A follow-up hardening plan should prioritise patch level and backups.",
    ]
    for line in findings:
        c.drawString(18 * mm, y, line[:110])
        y -= 6 * mm

    notes = tech.get("notes") or []
    if notes:
        y -= 3 * mm
        c.setFont("Helvetica-Oblique", 9)
        for note in notes[:3]:
            c.drawString(18 * mm, y, f"Note: {note}"[:110])
            y -= 5 * mm

    _footer(c, width, 1)
    pages += 1
    c.showPage()

    # --- Page 2: Recommendations ---
    y = _draw_logos(c, campaign, width, height)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(18 * mm, y, "Prioritised recommendations")
    y -= 10 * mm

    recommendations = [
        (
            "Confirm ownership",
            "Document who manages hosting, DNS, CMS admin, and SSL renewal for this URL.",
        ),
        (
            "Patch the stack",
            f"Validate whether {php_version} and {cms} are on currently supported releases.",
        ),
        (
            "Reduce fingerprinting",
            "Limit unnecessary Server / X-Powered-By disclosure where the host allows.",
        ),
        (
            "Harden access",
            "Enforce HTTPS, MFA for CMS admins, and restrict wp-admin /login paths if applicable.",
        ),
        (
            "Backup & monitor",
            "Verify offsite backups and uptime alerts before peak enrolment or campaign periods.",
        ),
    ]
    for title, body in recommendations:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(18 * mm, y, title)
        y -= 5.5 * mm
        c.setFont("Helvetica", 10)
        c.drawString(22 * mm, y, body[:105])
        y -= 9 * mm

    y -= 2 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(18 * mm, y, "Injected variables")
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    for key in ("business_name", "server_type", "php_version", "url"):
        c.drawString(18 * mm, y, f"{{{key}}} = {variables[key]}"[:110])
        y -= 5 * mm

    y -= 6 * mm
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(18 * mm, y, f"Branding: {_branding_line(campaign)}")

    _footer(c, width, 2)
    pages += 1
    c.save()

    if pages != TOTAL_PAGES:
        print(f"[pdf] Warning: expected {TOTAL_PAGES} pages, wrote {pages}")
    return out_path


def _fill_template_placeholders(
    doc: Any,
    replacements: dict[str, str],
    *,
    text_color: tuple[float, float, float] = (0.12, 0.16, 0.28),
) -> None:
    """
    Replace literal placeholder tokens in a designed template PDF in-place.
    Preserves original layout/colors/logo; only swaps placeholder glyphs.
    Prefer longer composite needles (e.g. `{city}, Australia`) so expanded
    values do not truncate against following static text.
    """
    items = sorted(replacements.items(), key=lambda kv: len(kv[0]), reverse=True)
    for page in doc:
        jobs: list[tuple[Any, str, float]] = []
        covered: list[Any] = []

        def _overlaps(rect: Any) -> bool:
            for prev in covered:
                inter = rect & prev
                if float(inter.width) > 0.5 and float(inter.height) > 0.5:
                    return True
            return False

        for needle, value in items:
            for rect in page.search_for(needle):
                if _overlaps(rect):
                    continue
                fontsize = max(7.0, float(rect.height) * 0.85)
                # Redact exact needle only — never widen (would erase static design text)
                jobs.append((rect, value, fontsize))
                covered.append(rect)
        if not jobs:
            continue
        for rect, _value, _fs in jobs:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        # images=0 keeps embedded Growva logo from the template
        page.apply_redactions(images=0)
        for rect, value, fontsize in jobs:
            page.insert_text(
                (rect.x0, rect.y1 - max(0.5, fontsize * 0.12)),
                value,
                fontsize=fontsize,
                fontname="helv",
                color=text_color,
            )


def build_reviews_audit_pdf(
    lead: dict[str, Any],
    output_dir: Path | None = None,
) -> Path | None:
    """
    Australia Growva Email 2: clone the official Growva Google Reviews Audit
    template (audit-pdfs-templetes/) and inject lead variables — same design,
    colors, and logo as the provided template. No layout redesign.
    """
    template = config.GROWVA_REVIEWS_AUDIT_TEMPLATE
    if not template.exists():
        print(f"[pdf] Missing Growva reviews template: {template}")
        return None

    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError:
            print("[pdf] Install pymupdf to fill the Growva reviews audit template.")
            return None

    output_dir = output_dir or config.REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    business_name = str(lead.get("business_name") or "Your Business")
    city = str(lead.get("city") or "your area")
    try:
        rating_val = float(lead.get("rating") or 0)
        rating = f"{rating_val:.1f}" if rating_val else "n/a"
    except (TypeError, ValueError):
        rating = str(lead.get("rating") or "n/a")
    try:
        review_count = str(int(float(lead.get("review_count") or 0)))
    except (TypeError, ValueError):
        review_count = str(lead.get("review_count") or "0")

    out_path = output_dir / f"{_safe_filename(business_name)}_reviews_audit.pdf"
    doc = pymupdf.open(str(template))
    try:
        # Composite phrases first (longer keys win) so layout stays exact
        _fill_template_placeholders(
            doc,
            {
                "{city}, Australia": f"{city}, Australia",
                "{rating} / 5.0 Stars": f"{rating} / 5.0 Stars",
                "{rating} Stars": f"{rating} Stars",
                "{review_count} Reviews": f"{review_count} Reviews",
                "Operational Impact for {business_name}": (
                    f"Operational Impact for {business_name}"
                ),
                "tailored to {business_name}.": f"tailored to {business_name}.",
                "tailored to {business_name}": f"tailored to {business_name}",
                "Target: {business_name}": f"Target: {business_name}",
                "{business_name}'s": f"{business_name}'s",
                "{business_name}": business_name,
                "{city}": city,
                "{rating}": rating,
                "{review_count}": review_count,
            },
        )
        doc.save(str(out_path), garbage=4, deflate=True)
    finally:
        doc.close()

    return out_path


def build_report(
    lead: dict[str, Any],
    tech: dict[str, Any],
    output_dir: Path | None = None,
) -> Path | None:
    """Backwards-compatible alias for custom audit PDF."""
    return build_custom_audit_pdf(
        lead, tech, campaign=lead.get("campaign_type"), output_dir=output_dir
    )
