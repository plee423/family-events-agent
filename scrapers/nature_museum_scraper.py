"""Scraper for Peggy Notebaert Nature Museum (naturemuseum.org/events).

Two-pass approach:
  Pass 1 — Fetch the events index page(s) and collect event detail URLs.
            The index uses bare <a href="/events/slug"> links with no class names.
            Pagination is attempted via ?page=N query strings.
  Pass 2 — Fetch each event detail page and extract title + date from plain text.
            Date format on detail pages: "Weekday, Month DD, YYYY, HH:MMam-HH:MMpm"
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

_BASE_URL = "https://naturemuseum.org"
_INDEX_URL = "https://naturemuseum.org/events"
_LOCATION_NAME = "Peggy Notebaert Nature Museum"
_LOCATION_ADDRESS = "2430 N Cannon Dr, Chicago, IL 60614"

# Regex for dates like "Tuesday, March 24, 2026" or "March 24, 2026"
_DATE_RE = re.compile(
    r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+'
    r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
    r'\s+\d{1,2},?\s+\d{4}',
    re.IGNORECASE,
)

# Matches trailing end-time range: "11:00AM-12:00PM" → strip "-12:00PM"
_END_TIME_RE = re.compile(
    r'(\d{1,2}:\d{2}\s*(?:AM|PM))\s*[-–]\s*\d{1,2}:\d{2}\s*(?:AM|PM)',
    re.IGNORECASE,
)


class NatureMuseumScraper(BaseScraper):
    """
    Two-pass scraper for Peggy Notebaert Nature Museum events.

    Pass 1: collects /events/{slug} URLs from the index.
    Pass 2: fetches each event page and parses title + date.
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
        # Not used directly — scrape() owns the two-pass flow
        return []

    def scrape(self, source_config: dict) -> list[Event]:
        org_name = source_config.get("name", _LOCATION_NAME)
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "")
        cost_hint = source_config.get("cost", "varies (free days available)")
        max_pages = source_config.get("max_pages", 5)

        # ── Pass 1: collect event URLs ─────────────────────────────────────────
        event_urls = self._collect_event_urls(max_pages)
        self.logger.info("  Notebaert: collected %d event URLs", len(event_urls))

        # ── Pass 2: scrape each event page ─────────────────────────────────────
        events: list[Event] = []
        for url in event_urls:
            event = self._scrape_event_page(url, org_name, tags, age_hint, cost_hint)
            if event:
                events.append(event)
            time.sleep(self.request_delay)

        self.logger.info("  %s: found %d events", org_name, len(events))
        return events

    def _collect_event_urls(self, max_pages: int) -> list[str]:
        """Return deduplicated list of /events/{slug} URLs from the index."""
        seen: set[str] = set()
        urls: list[str] = []

        for page in range(max_pages):
            index_url = _INDEX_URL if page == 0 else f"{_INDEX_URL}?page={page}"
            try:
                html = self.fetch(index_url)
            except Exception as exc:
                self.logger.warning("Index fetch failed (page %d): %s", page, exc)
                break

            soup = BeautifulSoup(html, "lxml")
            found_new = False

            for a in soup.find_all("a", href=True):
                href: str = a["href"]
                # Match /events/some-slug — exclude the index itself and category pages
                if re.match(r'^/events/[a-z0-9][a-z0-9\-]+$', href) and href not in seen:
                    seen.add(href)
                    urls.append(urljoin(_BASE_URL, href))
                    found_new = True

            # If no new URLs on this page, pagination is exhausted
            if not found_new and page > 0:
                break

        return urls

    def _scrape_event_page(
        self,
        url: str,
        org_name: str,
        tags: list[str],
        age_hint: str,
        cost_hint: str,
    ) -> Event | None:
        try:
            html = self.fetch(url)
        except Exception as exc:
            self.logger.debug("Failed to fetch event page %s: %s", url, exc)
            return None

        soup = BeautifulSoup(html, "lxml")

        # Title — h1 on the event detail page
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
        if not title:
            return None

        # Date — search all text nodes for a date pattern
        date_start = None
        for text_node in soup.find_all(string=_DATE_RE):
            raw = str(text_node).strip()
            # Strip trailing end-time so dateutil parses only the start time
            cleaned = _END_TIME_RE.sub(r'\1', raw)
            try:
                date_start = dateutil_parser.parse(cleaned, fuzzy=True)
                break
            except Exception:
                continue

        if date_start is None:
            self.logger.debug("No parseable date on %s — skipping", url)
            return None

        # Description — grab the first substantial text block after the title
        description = ""
        for el in soup.find_all(["p", "div"]):
            text = el.get_text(strip=True)
            if len(text) > 60 and text != title:
                description = text[:500]
                break

        cost_raw = cost_hint
        is_free = _infer_free(cost_raw, title, description)

        return Event(
            title=title,
            date_start=date_start,
            org_name=org_name,
            location_name=_LOCATION_NAME,
            location_address=_LOCATION_ADDRESS,
            description=description,
            url=url,
            cost=cost_raw,
            is_free=is_free,
            age_range=age_hint,
            tags=list(tags),
            source_name=org_name,
        )
