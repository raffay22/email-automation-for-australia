"""Checks headers, server, PHP version, and CMS signals."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.exceptions import SSLError, Timeout

DEFAULT_TIMEOUT = 12
USER_AGENT = "GrowvaTechDetector/1.0 (+outreach-audit)"

# Stable keys always returned by detect()
RESULT_KEYS = (
    "url",
    "reachable",
    "server_type",
    "server",
    "powered_by",
    "php_version",
    "cms",
    "cms_hints",
    "status_code",
    "notes",
    "final_host",
)


def _normalize_url(website: str) -> str:
    website = (website or "").strip()
    if not website:
        return ""
    if not website.startswith(("http://", "https://")):
        website = "https://" + website
    return website


def _empty_result(url: str = "") -> dict[str, Any]:
    return {
        "url": url,
        "reachable": False,
        "server_type": "",
        "server": "",
        "powered_by": "",
        "php_version": "",
        "cms": "",
        "cms_hints": [],
        "status_code": None,
        "notes": [],
        "final_host": "",
    }


def detect(website: str) -> dict[str, Any]:
    """
    Probe a website and return tech signals for the PDF builder.
    Never raises — network/SSL/timeouts soft-fail into `notes`.
    """
    url = _normalize_url(website)
    result = _empty_result(url)
    if not url:
        result["notes"].append("No website provided")
        return result

    try:
        resp = requests.get(
            url,
            timeout=DEFAULT_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except Timeout:
        result["notes"].append("Request timed out")
        return result
    except SSLError as exc:
        result["notes"].append(f"SSL error: {exc}")
        return result
    except requests.RequestException as exc:
        result["notes"].append(f"Request failed: {exc}")
        return result

    try:
        result["reachable"] = True
        result["status_code"] = resp.status_code
        result["url"] = resp.url or url
        headers = {k.lower(): v for k, v in resp.headers.items()}

        server = headers.get("server", "")
        powered_by = headers.get("x-powered-by", "")
        generator = headers.get("x-generator", "")
        result["server"] = server
        result["powered_by"] = powered_by
        result["server_type"] = server or powered_by or "Unknown"

        result["php_version"] = _detect_php(headers, powered_by, server)
        hints = _detect_cms(resp.text, headers, generator)
        result["cms_hints"] = hints
        result["cms"] = hints[0] if hints else "Not detected"
        result["final_host"] = urlparse(resp.url).hostname or ""
    except Exception as exc:  # parsing should never break the caller
        result["notes"].append(f"Parse error: {exc}")

    return result


def _detect_php(headers: dict[str, str], powered_by: str, server: str) -> str:
    php_match = re.search(r"PHP/?([\d.]+)", powered_by, re.I)
    if not php_match:
        php_match = re.search(r"PHP/?([\d.]+)", server, re.I)
    if php_match:
        return php_match.group(1)

    # Cookie hint when version banner is hidden
    set_cookie = headers.get("set-cookie", "")
    if re.search(r"\bphpsessid\b", set_cookie, re.I):
        return "detected (PHPSESSID cookie; version unknown)"
    if "php" in powered_by.lower():
        return "detected (version unknown)"
    return ""


def _detect_cms(html: str, headers: dict[str, str], generator_header: str = "") -> list[str]:
    hints: list[str] = []
    soup = BeautifulSoup(html or "", "html.parser")
    body = (html or "")[:25000].lower()

    meta_gen = ""
    tag = soup.find("meta", attrs={"name": re.compile(r"generator", re.I)})
    if tag and tag.get("content"):
        meta_gen = str(tag["content"])

    checks = [
        ("WordPress", ["wp-content", "wp-includes", "wordpress", "/wp-json/", "woocommerce"]),
        ("Drupal", ["drupal.settings", "sites/default/files", "drupal", "drupal.js"]),
        ("Joomla", ["joomla", "/media/jui/", "com_content"]),
        ("Shopify", ["cdn.shopify.com", "shopify"]),
        ("Wix", ["wixstatic.com", "wix.com"]),
        ("Squarespace", ["squarespace", "static.squarespace"]),
        ("Ghost", ["ghost.org", "ghost-"]),
        ("Webflow", ["webflow"]),
    ]
    for name, needles in checks:
        if any(n in body for n in needles):
            hints.append(name)

    combined = f"{generator_header} {headers.get('x-generator', '')} {meta_gen}".lower()
    for name, _ in checks:
        if name.lower() in combined and name not in hints:
            hints.append(name)

    # Meta generator often includes versioned product names
    if meta_gen and "wordpress" in meta_gen.lower() and "WordPress" not in hints:
        hints.insert(0, "WordPress")

    seen: set[str] = set()
    ordered: list[str] = []
    for h in hints:
        if h not in seen:
            seen.add(h)
            ordered.append(h)
    return ordered
