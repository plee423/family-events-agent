"""API scraper for organizations with public JSON endpoints."""
from __future__ import annotations

import logging
import time

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
from dateutil import parser as dateutil_parser

from .base import BaseScraper, Event, _infer_free

logger = logging.getLogger(__name__)


class ApiScraper(BaseScraper):
    """
    Fetches JSON from a public API endpoint and maps fields to Event objects.
    Field mappings are configured in sources.yaml under `field_map`.

    Example sources.yaml entry:
      scraper: "api"
      url: "https://example.org/api/events?type=family"
      field_map:
        events_path: "data.events"   # dot-path to the events list in JSON
        title: "name"
        date_start: "startDate"
        date_end: "endDate"
        location_name: "venue.name"
        location_address: "venue.address"
        description: "description"
        url: "eventUrl"
        cost: "price"
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
        import json

        org_name = source_config.get("name", "Unknown")
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "")
        cost_hint = source_config.get("cost", "")
        field_map = source_config.get("field_map", {})

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            self.logger.error("Invalid JSON from %s: %s", org_name, exc)
            return []

        # Navigate to events list using dot-path
        events_path = field_map.get("events_path", "")
        raw_list = data
        if events_path:
            for key in events_path.split("."):
                if isinstance(raw_list, dict):
                    raw_list = raw_list.get(key, [])
                else:
                    raw_list = []
                    break

        if not isinstance(raw_list, list):
            self.logger.warning("Expected a list at path %r for %s, got %s", events_path, org_name, type(raw_list))
            return []

        events: list[Event] = []
        for item in raw_list:
            title = _get_nested(item, field_map.get("title", "title"), "")
            if not title:
                continue

            date_str = _get_nested(item, field_map.get("date_start", "startDate"), "")
            date_start = None
            if date_str:
                try:
                    date_start = dateutil_parser.parse(str(date_str), fuzzy=True)
                except Exception:
                    pass
            if date_start is None:
                continue

            date_end_str = _get_nested(item, field_map.get("date_end", "endDate"), "")
            date_end = None
            if date_end_str:
                try:
                    date_end = dateutil_parser.parse(str(date_end_str), fuzzy=True)
                except Exception:
                    pass

            location_name = _get_nested(item, field_map.get("location_name", "venue"), "")
            location_address = _get_nested(item, field_map.get("location_address", "address"), "")
            description = _get_nested(item, field_map.get("description", "description"), "")
            url = _get_nested(item, field_map.get("url", "url"), "")
            cost_raw = _get_nested(item, field_map.get("cost", "price"), cost_hint)
            cost = str(cost_raw) if cost_raw else cost_hint

            is_free = _infer_free(cost, title, description)

            events.append(
                Event(
                    title=str(title),
                    date_start=date_start,
                    date_end=date_end,
                    org_name=org_name,
                    location_name=str(location_name),
                    location_address=str(location_address),
                    description=str(description),
                    url=str(url),
                    cost=cost,
                    is_free=is_free,
                    age_range=age_hint,
                    tags=list(tags),
                    source_name=source_config.get("name", org_name),
                )
            )

        return events


def _get_nested(obj: dict, dot_path: str, default="") -> str:
    """Traverse a dot-separated path through nested dicts."""
    if not dot_path:
        return default
    parts = dot_path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part, default)
        else:
            return default
    return current if current is not None else default
