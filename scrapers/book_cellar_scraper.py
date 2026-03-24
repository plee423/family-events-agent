"""Scraper for The Book Cellar (bookcellarinc.com).

The calendar page is server-rendered Drupal — no JS required.
Structure: <h3>Day, Month DD YYYY</h3> date headers with sibling
<ul><li> event entries. Standard parse_with_selectors() can't handle
this because the date and events are siblings, not parent/child.
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event, _infer_free

logger = logging.getLogger(__name__)

_BASE = "https://www.bookcellarinc.com"
_LOCATION_ADDRESS = "4736 N Lincoln Ave, Chicago, IL 60625"


class BookCellarScraper(BaseScraper):
    """
    Scrapes The Book Cellar's event calendar.

    The page uses a Drupal calendar module with this structure:
        <h3>Monday, March 02, 2026</h3>
        <ul>
          <li><a href="/event-slug">6:00 pm - Event Title</a></li>
        </ul>

    Date headers and event lists are siblings — requires sequential parsing.
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
        org_name = source_config.get("name", "The Book Cellar")
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "")
        cost_hint = source_config.get("cost", "free")

        soup = BeautifulSoup(content, "lxml")
        events: list[Event] = []

        # Walk all h3 elements — date headers look like "Monday, March 02, 2026"
        for h3 in soup.find_all("h3"):
            date_text = h3.get_text(strip=True)
            if not re.search(r'\b\d{4}\b', date_text):
                continue  # not a date header

            # The next sibling ul holds the events for this date
            ul = h3.find_next_sibling("ul")
            if not ul:
                continue

            for li in ul.find_all("li"):
                a_tag = li.find("a")
                if not a_tag:
                    continue

                li_text = li.get_text(strip=True)
                href = a_tag.get("href", "")

                # li text is often "6:00 pm - Event Title" — split on first " - "
                time_match = re.match(
                    r'^(\d{1,2}:\d{2}\s*(?:am|pm))\s*[-–]\s*(.+)$',
                    li_text,
                    re.IGNORECASE,
                )
                if time_match:
                    time_str = time_match.group(1).strip()
                    title = time_match.group(2).strip()
                    date_str = f"{date_text} {time_str}"
                else:
                    title = a_tag.get_text(strip=True)
                    date_str = date_text

                if not title:
                    continue

                try:
                    date_start = dateutil_parser.parse(date_str, fuzzy=True)
                except Exception:
                    continue

                full_url = urljoin(_BASE, href) if href else ""
                cost_raw = cost_hint
                is_free = _infer_free(cost_raw, title, "")

                events.append(Event(
                    title=title,
                    date_start=date_start,
                    org_name=org_name,
                    location_name="The Book Cellar",
                    location_address=_LOCATION_ADDRESS,
                    url=full_url,
                    cost=cost_raw,
                    is_free=is_free,
                    age_range=age_hint,
                    tags=list(tags),
                    source_name=org_name,
                ))

        self.logger.info("  %s: found %d events", org_name, len(events))
        return events
