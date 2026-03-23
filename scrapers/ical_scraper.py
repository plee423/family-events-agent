"""iCal scraper for organizations that publish .ics feeds directly."""
from __future__ import annotations

import logging
import time

import requests
from icalendar import Calendar
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event, _infer_free

logger = logging.getLogger(__name__)


class IcalScraper(BaseScraper):
    """
    Parses standard .ics feeds and maps VEVENT fields to our Event dataclass.
    Use for sources that already publish a calendar feed — no HTML parsing needed.
    """

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

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

        try:
            cal = Calendar.from_ical(content)
        except Exception as exc:
            self.logger.error("Failed to parse iCal feed for %s: %s", org_name, exc)
            return []

        events: list[Event] = []
        for component in cal.walk():
            if component.name != "VEVENT":
                continue

            summary = str(component.get("SUMMARY", "")).strip()
            if not summary:
                continue

            # Start date
            dtstart = component.get("DTSTART")
            if dtstart is None:
                continue
            date_start = dtstart.dt
            # Convert date → datetime if needed
            from datetime import date, datetime
            if isinstance(date_start, date) and not isinstance(date_start, datetime):
                date_start = datetime(date_start.year, date_start.month, date_start.day)

            # End date
            dtend = component.get("DTEND")
            date_end = None
            if dtend:
                date_end = dtend.dt
                if isinstance(date_end, date) and not isinstance(date_end, datetime):
                    date_end = datetime(date_end.year, date_end.month, date_end.day)

            location_raw = str(component.get("LOCATION", "")).strip()
            description = str(component.get("DESCRIPTION", "")).strip()
            url = str(component.get("URL", "")).strip()

            # Categories from the iCal feed
            cats = component.get("CATEGORIES")
            extra_tags = []
            if cats:
                if hasattr(cats, "__iter__") and not isinstance(cats, str):
                    for cat in cats:
                        extra_tags.extend(str(cat).split(","))
                else:
                    extra_tags = str(cats).split(",")
            merged_tags = list(tags) + [t.strip() for t in extra_tags if t.strip()]

            is_free = _infer_free(cost_hint, summary, description)

            events.append(
                Event(
                    title=summary,
                    date_start=date_start,
                    date_end=date_end,
                    org_name=org_name,
                    location_name=location_raw,
                    description=description,
                    url=url,
                    cost=cost_hint,
                    is_free=is_free,
                    age_range=age_hint,
                    tags=merged_tags,
                    source_name=source_config.get("name", org_name),
                )
            )

        return events
