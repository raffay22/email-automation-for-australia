"""Fallback scraper for Australia cities (Apify or offline fixture)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import config
import database

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _first_str(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, list):
            for item in value:
                text = str(item or "").strip()
                if text:
                    return text
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _city_matches(item_city: str, requested_city: str) -> bool:
    """Case-insensitive city match; also accept when requested city appears in address text."""
    requested = (requested_city or "").strip().lower()
    if not requested:
        return True
    candidate = (item_city or "").strip().lower()
    if not candidate:
        return True
    return requested == candidate or requested in candidate or candidate in requested


def normalize_apify_item(item: dict[str, Any], requested_city: str) -> dict[str, Any] | None:
    """Map common Apify lead fields onto the shared lead shape (incl. review metadata)."""
    # Always archive raw Apify payload first (even if later filtered for email)
    database.append_apify_raw(item, city=requested_city)

    business_name = _first_str(
        item.get("title"),
        item.get("name"),
        item.get("business_name"),
        item.get("school_name"),
    )
    url = _first_str(item.get("website"), item.get("websiteUrl"))
    # Prefer website for outreach; maps URL kept separately
    maps_url = _first_str(item.get("maps_url"), item.get("googleMapsUrl"), item.get("placeUrl"), item.get("url"))
    if not url and maps_url and "google.com/maps" not in maps_url.lower():
        url = maps_url
    email = _first_str(item.get("email"), item.get("emails"), item.get("mail")).lower()
    item_city = _first_str(
        item.get("city"),
        item.get("addressCity"),
        item.get("location"),
        item.get("address"),
    )
    category = _first_str(item.get("category"), item.get("categoryName"), item.get("type"))
    rating = _first_str(item.get("rating"), item.get("totalScore"), item.get("stars"))
    review_count = _first_str(
        item.get("review_count"),
        item.get("reviewsCount"),
        item.get("reviews"),
        item.get("totalReviews"),
    )
    phone = _first_str(item.get("phone"), item.get("phoneNumber"), item.get("telephone"))
    socials = item.get("socials") or item.get("socialMedia") or {}
    instagram = _first_str(item.get("instagram"))
    if not instagram and isinstance(socials, dict):
        instagram = str(socials.get("instagram") or "").strip()

    if not _city_matches(item_city, requested_city):
        return None
    if not email and not url:
        # Still archived in raw CSV; skip email outreach without contact surface
        return None
    if email and not EMAIL_RE.match(email):
        email = ""
        if not url:
            return None
    if not business_name:
        return None

    return {
        "business_name": business_name,
        "email": email,
        "url": url or maps_url,
        "city": requested_city,
        "campaign_type": "australia",
        "source": "apify",
        "category": category,
        "rating": rating,
        "review_count": review_count or "0",
        "phone": phone,
        "maps_url": maps_url,
        "instagram": instagram,
    }


def _load_fixture_items(city: str) -> list[dict[str, Any]]:
    path = config.APIFY_DRY_FIXTURE_PATH
    if not path or not Path(path).exists():
        return []
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[apify] Fixture load failed: {exc}")
        return []

    if isinstance(raw, dict):
        if city in raw and isinstance(raw[city], list):
            return list(raw[city])
        for key, value in raw.items():
            if str(key).lower() == city.lower() and isinstance(value, list):
                return list(value)
        if isinstance(raw.get("items"), list):
            return list(raw["items"])
        return []
    if isinstance(raw, list):
        return list(raw)
    return []


def _fetch_actor_items(city: str) -> list[dict[str, Any]]:
    if not config.APIFY_API_TOKEN or not config.APIFY_ACTOR_ID:
        print(f"[apify] Skipping {city}: missing APIFY_API_TOKEN or APIFY_ACTOR_ID")
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        print("[apify] Install apify-client to enable fallback scraping.")
        return []

    client = ApifyClient(config.APIFY_API_TOKEN)
    # compass/crawler-google-places requires at least one of:
    # searchStringsArray | categoryFilterWords | startUrls | allPlacesNoSearchAction
    run_input = {
        "searchStringsArray": [
            f"hair salon {city} Australia",
            f"gym {city} Australia",
            f"cafe {city} Australia",
        ],
        "maxCrawledPlacesPerSearch": 20,
        "language": "en",
        "countryCode": "au",
        "city": city,
        "maxResults": 50,
        "maxItems": 50,
    }
    try:
        run = client.actor(config.APIFY_ACTOR_ID).call(run_input=run_input)
    except Exception as exc:
        print(f"[apify] Actor run failed for {city}: {exc}")
        return []
    if not run:
        return []

    # apify-client may return a dict or a Run model
    if isinstance(run, dict):
        dataset_id = run.get("defaultDatasetId")
        status = (run.get("status") or "").upper()
    else:
        dataset_id = getattr(run, "default_dataset_id", None) or getattr(
            run, "defaultDatasetId", None
        )
        status = str(getattr(run, "status", "") or "").upper()

    if status and status not in {"SUCCEEDED", "COMPLETED"}:
        print(f"[apify] Actor status {status or 'unknown'} for {city}; skipping dataset")
        return []
    if not dataset_id:
        print(f"[apify] No dataset id for {city}; skipping")
        return []

    try:
        return list(client.dataset(dataset_id).iterate_items())
    except Exception as exc:
        print(f"[apify] Dataset read failed for {city}: {exc}")
        return []


def scrape_australia_city(city: str) -> list[dict[str, Any]]:
    """
    Collect Australia leads for one city via fixture or Apify.
    Skips any lead whose url or business_name is already in history.
    """
    if config.APIFY_DRY_FIXTURE_PATH:
        print(f"[apify] Fixture mode for {city}: {config.APIFY_DRY_FIXTURE_PATH}")
        raw_items = _load_fixture_items(city)
    else:
        raw_items = _fetch_actor_items(city)

    leads: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        lead = normalize_apify_item(item, requested_city=city)
        if not lead:
            continue
        if database.is_already_processed(lead["url"], lead["business_name"]):
            print(f"[apify] Dedupe skip: {lead['business_name']} / {lead['url']}")
            continue
        leads.append(lead)
    return leads


def scrape_australia_fallback(
    cities: list[str] | None = None,
    needed: int | None = None,
) -> list[dict[str, Any]]:
    """
    Australia-only city-wise fallback.

    When `needed` is set, stop starting *new* cities once enough leads are
    collected, but keep the full batch from the last scraped city so excess
    leads can be queued to the local backlog (no silent discard).
    """
    cities = cities or config.AUSTRALIA_FALLBACK_CITIES
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_names: set[str] = set()

    for city in cities:
        if needed is not None and len(results) >= needed:
            break
        print(f"[apify] Scraping city: {city}")
        for lead in scrape_australia_city(city):
            n_url = database.normalize_url(lead.get("url", ""))
            n_name = database.normalize_name(lead.get("business_name", ""))
            if n_url and n_url in seen_urls:
                continue
            if n_name and n_name in seen_names:
                continue
            if n_url:
                seen_urls.add(n_url)
            if n_name:
                seen_names.add(n_name)
            results.append(lead)
    print(f"[apify] Fallback collected {len(results)} lead(s)")
    return results
