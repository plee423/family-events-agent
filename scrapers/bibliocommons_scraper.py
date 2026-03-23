"""
Dedicated scraper for Bibliocommons library event APIs.
Used by Chicago Public Library (and optionally Irvine PL which also uses Bibliocommons).

API base: https://gateway.bibliocommons.com/v2/libraries/{library_id}/events
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from html import unescape
import re

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event

logger = logging.getLogger(__name__)

# Stable CPL audience IDs (verified from API response 2026-03-22)
_BABY_AUDIENCE_IDS = {
    "53f250153860d1000000000d",  # Babies: 0 to 18 months
    "53f250153860d1000000000e",  # Toddlers: 18 to 36 months
    "53f250153860d1000000000f",  # Preschoolers: 3 to 5 years
}
_ADULT_AUDIENCE_ID = "53f250153860d10000000012"  # Adults: 18 and up

# Audience ID → age_range string
_AUDIENCE_AGE_MAP = {
    "53f250153860d1000000000d": "0-18 months",
    "53f250153860d1000000000e": "18-36 months",
    "53f250153860d1000000000f": "36-60 months",
    "53f250153860d10000000012": "adults",
}


class BibliocommunesScraper(BaseScraper):
    """
    Fetches events from the Bibliocommons JSON gateway API.

    Required source config keys:
        library_id: "chipublib"  (the subdomain on bibliocommons.com)
        audiences: "babies_and_toddlers"  (comma-separated, optional)
        types: "storytime"  (comma-separated, optional)
        branch_filter: ["Near North", "Harold Washington"]  (optional, filter to specific branches)
    """

    BASE = "https://gateway.bibliocommons.com/v2/libraries/{library_id}"

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        })
        self._branch_cache: dict[str, str] = {}  # id → name

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _get(self, url: str, params: dict = None) -> dict:
        time.sleep(0.25)  # API calls can be faster than HTML scraping
        resp = self.session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _fetch_branches(self, library_id: str) -> dict[str, str]:
        """Return {branch_id: branch_name} mapping."""
        if self._branch_cache:
            return self._branch_cache
        url = self.BASE.format(library_id=library_id) + "/branches"
        try:
            data = self._get(url)
            branches = data.get("entities", {}).get("branches", {})
            self._branch_cache = {k: v.get("name", k) for k, v in branches.items()}
        except Exception as exc:
            logger.warning("Could not fetch branch names: %s", exc)
        return self._branch_cache

    def fetch(self, url: str) -> str:
        # Not used directly — we override scrape() instead
        return ""

    def parse(self, content: str, source_config: dict) -> list[Event]:
        # Not used directly
        return []

    def scrape(self, source_config: dict) -> list[Event]:
        """Override: use the API directly instead of fetch+parse."""
        library_id = source_config.get("library_id", "chipublib")
        audiences = source_config.get("audiences", "babies_and_toddlers")
        event_types = source_config.get("event_types", "")
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "0-60 months")
        org_name = source_config.get("name", "Chicago Public Library")
        branch_filter = source_config.get("branch_filter", [])  # [] = all branches

        base_url = self.BASE.format(library_id=library_id) + "/events"
        branches = self._fetch_branches(library_id)

        # NOTE: CPL API does not sort by date and ignores audience/type filters server-side.
        # We fetch up to max_pages pages and rely on the downstream date+age filters.
        # At 10 events/page, 50 pages = 500 events — a solid statistical sample of
        # upcoming events across all 80+ branches.
        max_pages = source_config.get("max_pages", 50)

        params = {"page": 1}
        if audiences:
            params["audiences"] = audiences
        if event_types:
            params["types"] = event_types

        all_events: list[Event] = []
        page = 1
        total_pages = 1

        while page <= total_pages and page <= max_pages:
            params["page"] = page
            try:
                data = self._get(base_url, params)
            except Exception as exc:
                logger.error("API fetch failed page %d for %s: %s", page, org_name, exc)
                break

            pagination = data.get("events", {}).get("pagination", {})
            total_pages = pagination.get("pages", 1)
            item_ids = data.get("events", {}).get("items", [])
            events_map = data.get("entities", {}).get("events", {})

            for event_id in item_ids:
                event_data = events_map.get(event_id)
                if not event_data:
                    continue
                event = self._parse_event(event_data, org_name, tags, age_hint, branches)
                if event:
                    all_events.append(event)

            page += 1

        # Apply branch filter if specified
        if branch_filter:
            bf_lower = [b.lower() for b in branch_filter]
            all_events = [
                e for e in all_events
                if any(b in e.location_name.lower() for b in bf_lower)
            ]

        self.logger.info("  %s: found %d events", org_name, len(all_events))
        return all_events

    def _parse_event(
        self, data: dict, org_name: str, tags: list, age_hint: str, branches: dict
    ) -> Event | None:
        defn = data.get("definition", {})

        title = defn.get("title", "").strip()
        if not title or defn.get("isCancelled"):
            return None

        # Audience filtering: skip events that are only for adults
        audience_ids = set(defn.get("audienceIds", []))
        if audience_ids:
            has_family = bool(audience_ids & _BABY_AUDIENCE_IDS)
            only_adult = audience_ids == {_ADULT_AUDIENCE_ID}
            if only_adult:
                return None  # skip pure adult events
            # Determine age_range from audiences
            age_range = _audiences_to_age_range(audience_ids) or age_hint
        else:
            age_range = age_hint  # no audience info → use source-level hint

        # Dates
        start_str = defn.get("start", "")
        end_str = defn.get("end", "")
        if not start_str:
            return None
        try:
            date_start = datetime.fromisoformat(start_str)
            date_end = datetime.fromisoformat(end_str) if end_str else None
        except ValueError:
            return None

        # Branch / location
        branch_id = defn.get("branchLocationId", "")
        location_name = branches.get(branch_id, f"CPL Branch {branch_id}")
        if branch_id:
            location_name = f"CPL {location_name}"

        # Description — strip HTML tags
        raw_desc = defn.get("description", "")
        description = _strip_html(raw_desc)

        # URL
        url = f"https://chipublib.bibliocommons.com/events/{data['id']}"

        return Event(
            title=title,
            date_start=date_start,
            date_end=date_end,
            org_name=org_name,
            location_name=location_name,
            description=description[:500],
            url=url,
            cost="free",
            is_free=True,
            age_range=age_range,
            tags=list(tags),
            source_name=org_name,
        )


def _audiences_to_age_range(audience_ids: set) -> str:
    """Convert a set of audience IDs to a human-readable age range string."""
    ranges = [_AUDIENCE_AGE_MAP[aid] for aid in audience_ids if aid in _AUDIENCE_AGE_MAP and aid != _ADULT_AUDIENCE_ID]
    if not ranges:
        return ""
    # Build a combined range: take min of lowers and max of uppers
    import re
    months = []
    for r in ranges:
        m = re.match(r"(\d+)-(\d+)\s*(months?|years?)", r)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if "year" in m.group(3):
                lo *= 12; hi *= 12
            months.append((lo, hi))
    if not months:
        return ", ".join(ranges)
    lo = min(m[0] for m in months)
    hi = max(m[1] for m in months)
    return f"{lo}-{hi} months"


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
