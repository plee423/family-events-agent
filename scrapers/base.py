"""Base scraper class and Event dataclass shared across all scrapers."""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Represents a single family event discovered from any source."""

    title: str
    date_start: datetime
    org_name: str

    # Optional fields
    date_end: Optional[datetime] = None
    location_name: str = ""
    location_address: str = ""
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    description: str = ""
    url: str = ""
    cost: str = ""          # "free", "$10", "free (IL residents)", etc.
    is_free: bool = False
    age_range: str = ""     # "0-24 months", "all ages", etc.
    tags: list[str] = field(default_factory=list)
    distance_miles: Optional[float] = None
    source_name: str = ""

    @property
    def uid(self) -> str:
        """Deterministic UID — stable across runs so re-importing doesn't duplicate."""
        raw = f"{self.title}|{self.date_start.isoformat()}|{self.location_name}|{self.org_name}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    @property
    def display_title(self) -> str:
        """Title with free indicator prepended when applicable."""
        prefix = "[FREE] " if self.is_free else ""
        return f"{prefix}{self.title}"

    def __repr__(self) -> str:
        return (
            f"Event(title={self.title!r}, date={self.date_start.date()}, "
            f"org={self.org_name!r}, free={self.is_free})"
        )


class BaseScraper(ABC):
    """Abstract base class that every scraper must implement."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.scraping_cfg = settings.get("scraping", {})
        self.user_agent = self.scraping_cfg.get(
            "user_agent", "FamilyEventsAgent/1.0 (personal family calendar tool)"
        )
        self.request_delay = float(self.scraping_cfg.get("request_delay_seconds", 1.0))
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def fetch(self, url: str) -> str:
        """Fetch raw content from URL. Returns raw HTML/text/data."""
        ...

    @abstractmethod
    def parse(self, content: str, source_config: dict) -> list[Event]:
        """Parse raw content into a list of Event objects."""
        ...

    def scrape(self, source_config: dict) -> list[Event]:
        """Full scrape pipeline: fetch → parse. Called by the agent."""
        url = source_config["url"]
        self.logger.debug("Fetching %s", url)
        content = self.fetch(url)
        events = self.parse(content, source_config)
        self.logger.info("  %s: found %d raw events", source_config["name"], len(events))
        return events


def parse_with_selectors(soup, source_config: dict, org_name: str, base_url: str) -> list[Event]:
    """
    Shared HTML parsing logic used by both HtmlScraper and BrowserScraper.
    Accepts a BeautifulSoup object and extracts events using CSS selectors from config.
    """
    from dateutil import parser as dateutil_parser

    selectors = source_config.get("selectors", {})
    tags = source_config.get("tags", [])
    age_hint = source_config.get("age_hint", "")
    cost_hint = source_config.get("cost", "")

    card_sel = selectors.get("event_card", "article")
    title_sel = selectors.get("title", "h2, h3")
    date_sel = selectors.get("date", ".date, time")
    time_sel = selectors.get("time", ".time")
    location_sel = selectors.get("location", ".location")
    link_sel = selectors.get("link", "a")
    desc_sel = selectors.get("description", ".description, p")

    cards = soup.select(card_sel)
    if not cards:
        logging.getLogger(__name__).debug(
            "No cards found with selector %r for %s", card_sel, org_name
        )
        return []

    events: list[Event] = []
    for card in cards:
        # Title
        title_el = card.select_one(title_sel)
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue

        # Date
        date_el = card.select_one(date_sel)
        date_str = ""
        if date_el:
            date_str = date_el.get("datetime") or date_el.get_text(strip=True)

        # Time (may be a separate element)
        time_el = card.select_one(time_sel) if time_sel else None
        if time_el and date_str:
            date_str = f"{date_str} {time_el.get_text(strip=True)}"

        date_start = None
        if date_str:
            try:
                date_start = dateutil_parser.parse(_clean_date_str(date_str), fuzzy=True)
            except Exception:
                pass

        if date_start is None:
            # No parseable date — skip
            continue

        # Location
        loc_el = card.select_one(location_sel) if location_sel else None
        location_name = loc_el.get_text(strip=True) if loc_el else org_name

        # Link — "self" means the card element itself is the <a> tag
        href = ""
        if link_sel == "self":
            href = card.get("href", "")
        else:
            link_el = card.select_one(link_sel) if link_sel else None
            if link_el:
                href = link_el.get("href", "")
        if href and not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin(base_url, href)

        # Description
        desc_el = card.select_one(desc_sel) if desc_sel else None
        description = desc_el.get_text(strip=True) if desc_el else ""

        is_free = _infer_free(cost_hint, title, description)

        events.append(
            Event(
                title=title,
                date_start=date_start,
                org_name=org_name,
                location_name=location_name or org_name,
                description=description,
                url=href,
                cost=cost_hint,
                is_free=is_free,
                age_range=age_hint,
                tags=list(tags),
                source_name=source_config.get("name", org_name),
            )
        )

    return events


def _clean_date_str(s: str) -> str:
    """Normalize date strings before passing to dateutil.
    Handles: day-of-week abbreviations, time ranges, date ranges with 'to'.
    Always keeps only the START date/time.
    """
    import re
    # Date ranges like "March 28, 2023 to May 30, 2023" → keep start only
    s = re.sub(r'(.+?)\s+to\s+\w.*', r'\1', s, flags=re.IGNORECASE)
    # Strip day-of-week abbreviations embedded in the string
    s = re.sub(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b', '', s)
    # Keep only start of time ranges: "10:00 AM - 11:00 AM" → "10:00 AM"
    s = re.sub(r'(\d{1,2}:\d{2}\s*(?:AM|PM))\s*[-–]\s*\d{1,2}:\d{2}\s*(?:AM|PM)', r'\1', s, flags=re.IGNORECASE)
    return s.strip()


def _infer_free(cost_hint: str, title: str, description: str) -> bool:
    """Return True if we can determine this event is free."""
    text = f"{cost_hint} {title} {description}".lower()
    free_indicators = ["free", "no cost", "no charge", "complimentary"]
    paid_overrides = ["$", "fee", "admission required", "tickets required"]
    if any(p in text for p in paid_overrides):
        return False
    return any(f in text for f in free_indicators)
