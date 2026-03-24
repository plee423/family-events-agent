"""Scraper for Chicago.gov AEM (Adobe Experience Manager) calendar JSON endpoints."""
from __future__ import annotations

import json
import logging
import re
import time

import requests
from dateutil import parser as dateutil_parser
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event, _infer_free

logger = logging.getLogger(__name__)


class ChicagoAemScraper(BaseScraper):
    """
    Fetches events from Chicago.gov AEM calendar JSON endpoints.

    These endpoints return double-encoded JSON:
        { "calendarData": "<json-string-of-event-array>" }

    The inner string must be JSON.parsed a second time to get the event list.
    Events are then filtered client-side by the 'tags' field.

    Configure in sources.yaml:
        scraper: chicago_aem
        url: "https://www.chicago.gov/content/city/en/depts/dca/supp_info/events2/jcr:content/parsys/fullcalendar/calendarData"
        tag_filter: "Millennium Park"   # or "Chicago Cultural Center"
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
        org_name = source_config.get("name", "Unknown")
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "")
        cost_hint = source_config.get("cost", "")
        tag_filter = source_config.get("tag_filter", "")

        # Parse response — AEM endpoints return either:
        #   A) { "calendarData": "<json-string>" }  → double-parse required
        #   B) A raw JSON array                     → use directly
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                events_list = parsed
            elif isinstance(parsed, dict):
                inner_str = parsed.get("calendarData", "[]")
                events_list = json.loads(inner_str)
            else:
                self.logger.warning("Unexpected AEM response type %s for %s", type(parsed), org_name)
                return []
        except json.JSONDecodeError as exc:
            self.logger.error("Failed to parse AEM JSON for %s: %s", org_name, exc)
            return []

        if not isinstance(events_list, list):
            self.logger.warning(
                "Expected list from AEM endpoint for %s, got %s", org_name, type(events_list)
            )
            return []

        events: list[Event] = []
        for item in events_list:
            # Filter by tag if configured
            if tag_filter and tag_filter not in (item.get("tags") or ""):
                continue

            title = (item.get("title") or "").strip()
            if not title:
                continue

            # Parse start date (ISO 8601 with offset)
            date_str = item.get("start") or item.get("eventStarts", "")
            try:
                date_start = dateutil_parser.parse(str(date_str))
            except Exception:
                continue

            # Parse end date
            date_end = None
            end_str = item.get("end") or item.get("eventEnds", "")
            if end_str:
                try:
                    date_end = dateutil_parser.parse(str(end_str))
                except Exception:
                    pass

            # Location from address fields
            addr_parts = [
                item.get("address1", ""),
                item.get("address2", ""),
                item.get("city", ""),
                item.get("state", ""),
                item.get("zip", ""),
            ]
            location_address = ", ".join(p for p in addr_parts if p)
            location_name = tag_filter or org_name

            # Resolve relative URLs
            event_url = item.get("url", "") or ""
            if event_url.startswith("/"):
                event_url = "https://www.chicago.gov" + event_url

            description = re.sub(r"<[^>]+>", "", item.get("description", "") or "").strip()

            # Merge tags from comma-separated AEM tags string
            extra_tags = [t.strip() for t in (item.get("tags") or "").split(",") if t.strip()]
            merged_tags = list(tags) + extra_tags

            is_free = _infer_free(cost_hint, title, description)

            events.append(Event(
                title=title,
                date_start=date_start,
                date_end=date_end,
                org_name=org_name,
                location_name=location_name,
                location_address=location_address,
                description=description,
                url=event_url,
                cost=cost_hint,
                is_free=is_free,
                age_range=age_hint,
                tags=merged_tags,
                source_name=source_config.get("name", org_name),
            ))

        return events
