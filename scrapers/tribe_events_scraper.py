"""Scraper for The Events Calendar (Tribe Events) WordPress REST API."""
from __future__ import annotations

import logging
import re
import time

import requests
from dateutil import parser as dateutil_parser
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event, _infer_free

logger = logging.getLogger(__name__)


class TribeEventsScraper(BaseScraper):
    """
    Fetches events from The Events Calendar (Tribe Events) WordPress REST API.
    Handles pagination automatically via the `next_rest_url` field in responses.

    Use for sources with:
        scraper: tribe_events
        url: "https://example.org/wp-json/tribe/events/v1/events"
    """

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        })

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def fetch(self, url: str) -> str:
        time.sleep(self.request_delay)
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        return resp.text

    def parse(self, content: str, source_config: dict) -> list[Event]:
        # Not called directly — scrape() owns the pagination loop
        return []

    def scrape(self, source_config: dict) -> list[Event]:
        """Paginate through all pages of the Tribe Events REST API."""
        import json

        org_name = source_config.get("name", "Unknown")
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "")
        cost_hint = source_config.get("cost", "")

        # Add per_page param if not already in URL
        base_url = source_config["url"]
        if "per_page" not in base_url:
            sep = "&" if "?" in base_url else "?"
            base_url += f"{sep}per_page=50"

        all_events: list[Event] = []
        url: str | None = base_url
        page = 0

        while url:
            page += 1
            self.logger.debug("Fetching page %d: %s", page, url)
            try:
                data = json.loads(self.fetch(url))
            except Exception as exc:
                self.logger.error("Failed to fetch/parse page %d for %s: %s", page, org_name, exc)
                break

            for item in data.get("events", []):
                title = (item.get("title") or "").strip()
                if not title:
                    continue

                try:
                    date_start = dateutil_parser.parse(item.get("start_date", ""))
                except Exception:
                    continue

                date_end = None
                if item.get("end_date"):
                    try:
                        date_end = dateutil_parser.parse(item["end_date"])
                    except Exception:
                        pass

                venue = item.get("venue") or {}
                location_name = venue.get("venue", "") or org_name
                location_address = ", ".join(
                    p for p in [
                        venue.get("address", ""),
                        venue.get("city", ""),
                        venue.get("state", ""),
                        venue.get("zip", ""),
                    ] if p
                )

                description = re.sub(r"<[^>]+>", "", item.get("description", "") or "").strip()
                event_url = item.get("url", "")
                cost_raw = str(item.get("cost") or cost_hint)
                is_free = _infer_free(cost_raw, title, description)

                all_events.append(Event(
                    title=title,
                    date_start=date_start,
                    date_end=date_end,
                    org_name=org_name,
                    location_name=location_name,
                    location_address=location_address,
                    description=description,
                    url=event_url,
                    cost=cost_raw,
                    is_free=is_free,
                    age_range=age_hint,
                    tags=list(tags),
                    source_name=source_config.get("name", org_name),
                ))

            url = data.get("next_rest_url") or None

        self.logger.info("  %s: found %d events across %d pages", org_name, len(all_events), page)
        return all_events
