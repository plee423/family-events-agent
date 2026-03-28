"""Scraper for the Field Museum events page via __NEXT_DATA__ JSON."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event, _infer_free

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.fieldmuseum.org"
_EVENTS_PAGE = f"{_BASE_URL}/our-events"


class FieldMuseumScraper(BaseScraper):
    """
    Scrapes Field Museum events from the __NEXT_DATA__ JSON embedded in the
    /our-events page.  No browser needed — plain HTTP request.

    The JSON lives at:
        <script id="__NEXT_DATA__" type="application/json">…</script>
    Path inside JSON:
        props.pageProps.allEvents  (list of ~64 event objects)

    Each event object has:
        title, start (ISO8601), end (ISO8601), slug, eventSeries.slug,
        description (HTML), childDescription (HTML), ticketing (cost string),
        ageGroups (str), audienceTags [{"tag": "Families"}, …]
    """

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml",
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
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            content,
            re.DOTALL,
        )
        if not m:
            self.logger.warning("No __NEXT_DATA__ found on Field Museum events page")
            return []

        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            self.logger.error("JSON decode error in __NEXT_DATA__: %s", exc)
            return []

        all_events = (
            data.get("props", {}).get("pageProps", {}).get("allEvents", [])
        )
        if not all_events:
            self.logger.warning("allEvents is empty in __NEXT_DATA__")
            return []

        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "")
        org_name = source_config.get("name", "Field Museum")

        events: list[Event] = []
        for item in all_events:
            title = (item.get("title") or "").strip()
            if not title:
                continue

            start_str = item.get("start") or ""
            if not start_str:
                continue
            try:
                date_start = dateutil_parser.parse(start_str)
            except Exception:
                continue

            end_str = item.get("end") or ""
            date_end = None
            if end_str:
                try:
                    date_end = dateutil_parser.parse(end_str)
                except Exception:
                    pass

            # Build URL from eventSeries.slug + slug
            slug = item.get("slug") or ""
            series = item.get("eventSeries") or {}
            series_slug = series.get("slug") or "" if series else ""
            if series_slug and slug:
                url = f"{_BASE_URL}/our-events/{series_slug}/{slug}"
            elif slug:
                url = f"{_BASE_URL}/our-events/{slug}"
            else:
                url = _EVENTS_PAGE

            # Strip HTML from description; prefer childDescription when available
            raw_desc = item.get("childDescription") or item.get("description") or ""
            description = BeautifulSoup(raw_desc, "lxml").get_text(separator=" ", strip=True)

            cost = (item.get("ticketing") or "").strip()
            is_free = _infer_free(cost, title, description)

            age_range = (item.get("ageGroups") or age_hint or "").strip()

            # Merge audience tags from the event data
            audience_tags = [
                t.get("tag", "") for t in (item.get("audienceTags") or []) if t.get("tag")
            ]
            event_tags = list(tags) + [t.lower().replace(" & ", "_").replace(" ", "_")
                                       for t in audience_tags if t]

            events.append(Event(
                title=title,
                date_start=date_start,
                date_end=date_end,
                org_name=org_name,
                location_name="Field Museum",
                location_address="1400 S Lake Shore Dr, Chicago, IL 60605",
                description=description,
                url=url,
                cost=cost,
                is_free=is_free,
                age_range=age_range,
                tags=event_tags,
                source_name=source_config.get("name", org_name),
            ))

        return events
