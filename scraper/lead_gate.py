"""Australia school/college detection and track tagging (fail-closed)."""

from __future__ import annotations

import re
from typing import Any

from generator.tech_detector import detect

# Strong education keywords (always school)
SCHOOL_STRONG_RE = re.compile(
    r"\b("
    r"school|college|university|campus|kindergarten|preschool|pre[\s-]?school|"
    r"primary\s+school|secondary\s+school|high\s*school|tafe|"
    r"institute\s+of\s+education|grammar|preparatory|prep\s+school|"
    r"public\s+school|private\s+school|catholic\s+school"
    r")\b",
    re.I,
)

# "academy" alone is too broad (dance/fitness academies) — only with education context
ACADEMY_EDU_RE = re.compile(
    r"\bacademy\b.*\b(school|college|education|university|learning)\b|"
    r"\b(school|college|education|university|learning)\b.*\bacademy\b",
    re.I,
)

EDU_CATEGORY_RE = re.compile(
    r"\b(school|college|university|education|kindergarten|preschool|tafe)\b",
    re.I,
)

PHP_CMS = {"wordpress", "joomla", "drupal"}


def is_school_or_college(lead: dict[str, Any]) -> bool:
    name = str(lead.get("business_name") or "")
    category = str(lead.get("category") or "")
    blob = f"{name} {category}"

    if SCHOOL_STRONG_RE.search(blob):
        return True
    if ACADEMY_EDU_RE.search(blob):
        return True
    # Bare "academy" only if category is clearly education
    if re.search(r"\bacademy\b", name, re.I) and EDU_CATEGORY_RE.search(category):
        return True
    if EDU_CATEGORY_RE.search(category) and re.search(
        r"\b(school|college|university|grammar)\b", name, re.I
    ):
        return True
    return False


def has_php_or_legacy_issue(tech: dict[str, Any] | None = None, url: str = "") -> bool:
    """
    True only with concrete PHP/legacy evidence:
      - non-empty php_version (incl. PHPSESSID detection text)
      - PHP in powered_by / server
      - CMS hint in {WordPress, Joomla, Drupal}
    """
    if tech is None:
        tech = detect(url) if url else {}

    php = str(tech.get("php_version") or "").strip()
    if php and php.lower() not in {"", "not detected", "n/a", "none"}:
        return True

    powered = str(tech.get("powered_by") or "")
    server = str(tech.get("server") or tech.get("server_type") or "")
    if re.search(r"\bphp\b|phpsessid", f"{powered} {server}", re.I):
        return True

    hints = [str(h).strip().lower() for h in (tech.get("cms_hints") or [])]
    cms = str(tech.get("cms") or "").strip().lower()
    if cms in PHP_CMS:
        return True
    if any(h in PHP_CMS for h in hints):
        return True
    return False


def require_australia_track(lead: dict[str, Any]) -> str | None:
    """Return explicit au_track only when growva or security; else None."""
    track = (lead.get("au_track") or "").strip().lower()
    if track in {"growva", "security"}:
        return track
    return None


def assign_australia_track(lead: dict[str, Any]) -> dict[str, Any] | None:
    """
    Tag AU leads:
      - service business → au_track=growva (6-email Growva sequence)
      - school + PHP/legacy → au_track=security (5-email tech sequence)
      - school without PHP/legacy → None (skip; do not email)
    """
    out = dict(lead)
    out["campaign_type"] = "australia"

    if not is_school_or_college(out):
        out["au_track"] = "growva"
        return out

    tech = out.get("_tech_cache")
    if not isinstance(tech, dict):
        tech = detect(out.get("url") or "")
    out["_tech_cache"] = tech

    if has_php_or_legacy_issue(tech):
        out["au_track"] = "security"
        print(
            f"[gate] AU school → security track (PHP/legacy): "
            f"{out.get('business_name')} / {out.get('url')}"
        )
        return out

    print(
        f"[gate] AU school SKIPPED (no PHP/legacy issue): "
        f"{out.get('business_name')} / {out.get('url')}"
    )
    return None
