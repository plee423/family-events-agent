"""Scraper for Tockify-powered event calendars."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event, _infer_free

logger = logging.getLogger(__name__)


class TockifyScraper(BaseScraper):
    """
    Fetches events from the Tockify REST API.
    Used for organizations that embed a Tockify calendar widget (e.g. Chicago Children's Museum).

    Configure in sources.yaml:
        scraper: tockify
        tockify_calendar: "chicagochildrensmuseum"
        location_name: "Chicago Children's Museum"       # optional display name
        location_address: "700 E Grand Ave, Chicago, IL 60611"  # optional fixed address
        max_per_page: 50   # optional, default 50
    """

    TOCKIFY_API = "https://api.tockify.com/api/ngevent"

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
        """Fetch all upcoming events from Tockify API, paginating via metaData.hasNext."""
        org_name = source_config.get("name", "Unknown")
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "")
        cost_hint = source_config.get("cost", "")
        cal_name = source_config.get("tockify_calendar", "")
        max_per_page = int(source_config.get("max_per_page", 50))
        location_name = source_config.get("location_name", org_name)
        location_address = source_config.get("location_address", "")
        website_fallback = source_config.get("website", "")

        if not cal_name:
            self.logger.error("tockify_calendar not configured for %s", org_name)
            return []

        # Start from now (Unix ms)
        start_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        all_events: list[Event] = []
        page = 0

        while True:
            page += 1
            url = f"{self.TOCKIFY_API}?calname={cal_name}&max={max_per_page}&startms={start_ms}"
            self.logger.debug("Fetching Tockify page %d: %s", page, url)

            try:
                data = json.loads(self.fetch(url))
            except Exception as exc:
                self.logger.error("Tockify fetch failed for %s page %d: %s", org_name, page, exc)
                break

            items = data.get("events", [])
            if not items:
                break

            last_end_ms = start_ms
            for item in items:
                when = item.get("when") or {}
                content_obj = item.get("content") or {}

                start_millis = (when.get("start") or {}).get("millis")
                if start_millis is None:
                    continue

                title = ((content_obj.get("summary") or {}).get("text") or "").strip()
                if not title:
                    continue

                date_start = datetime.fromtimestamp(start_millis / 1000, tz=timezone.utc)

                end_millis = (when.get("end") or {}).get("millis")
                date_end = None
                if end_millis:
                    date_end = datetime.fromtimestamp(end_millis / 1000, tz=timezone.utc)
                    last_end_ms = max(last_end_ms, end_millis)

                description = ((content_obj.get("description") or {}).get("text") or "")

                # Tags from Tockify tagset
                tagset_tags = ((content_obj.get("tagset") or {}).get("tags") or {}).get("default", [])
                merged_tags = list(tags) + [t for t in tagset_tags if t]

                is_free = _infer_free(cost_hint, title, description)

                all_events.append(Event(
                    title=title,
                    date_start=date_start,
                    date_end=date_end,
                    org_name=org_name,
                    location_name=location_name,
                    location_address=location_address,
                    description=description,
                    url=website_fallback,  # Tockify API doesn't return per-event URLs; fall back to org programs page
                    cost=cost_hint,
                    is_free=is_free,
                    age_range=age_hint,
                    tags=merged_tags,
                    source_name=source_config.get("name", org_name),
                ))

            # Advance cursor for next page
            start_ms = last_end_ms + 1

            meta = data.get("metaData") or {}
            if not meta.get("hasNext", False):
                break

        self.logger.info("  %s: found %d events across %d pages", org_name, len(all_events), page)
        return all_events
