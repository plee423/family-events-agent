"""Tests for the scraper layer."""
from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.base import Event, parse_with_selectors, _infer_free
from scrapers.html_scraper import HtmlScraper
from scrapers.ical_scraper import IcalScraper

# ── Fixtures ───────────────────────────────────────────────────────────────────

SETTINGS = {
    "scraping": {
        "user_agent": "TestAgent/1.0",
        "request_delay_seconds": 0,
        "cache_ttl_hours": 6,
    }
}

SOURCE_CONFIG = {
    "name": "Test Library",
    "url": "https://example.com/events",
    "scraper": "html",
    "selectors": {
        "event_card": ".event-card",
        "title": ".event-title",
        "date": ".event-date",
        "time": ".event-time",
        "location": ".event-location",
        "link": "a",
        "description": ".event-desc",
    },
    "tags": ["storytime", "baby"],
    "age_hint": "0-24 months",
    "cost": "free",
}

SAMPLE_HTML = """
<html><body>
  <div class="event-card">
    <h2 class="event-title"><a href="/events/1">Baby Storytime</a></h2>
    <span class="event-date">2026-04-05</span>
    <span class="event-time">10:00 AM</span>
    <span class="event-location">Main Branch</span>
    <p class="event-desc">Free storytime for babies 0-24 months.</p>
  </div>
  <div class="event-card">
    <h2 class="event-title"><a href="/events/2">Toddler Craft Hour</a></h2>
    <span class="event-date">2026-04-06</span>
    <span class="event-time">11:00 AM</span>
    <span class="event-location">North Branch</span>
  </div>
</body></html>
"""

SAMPLE_ICAL = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
SUMMARY:Baby Yoga Class
DTSTART:20260405T100000
DTEND:20260405T110000
LOCATION:Lincoln Park Community Center
DESCRIPTION:Fun yoga for babies and parents. Free!
URL:https://example.com/events/yoga
CATEGORIES:baby,yoga,family
END:VEVENT
BEGIN:VEVENT
SUMMARY:Adults Only Wine Tasting
DTSTART:20260405T190000
DTEND:20260405T210000
LOCATION:Downtown Wine Bar
DESCRIPTION:Evening event for adults only. $50/person.
END:VEVENT
END:VCALENDAR"""


# ── Event dataclass tests ─────────────────────────────────────────────────────

class TestEvent:
    def test_uid_is_deterministic(self):
        e1 = Event(
            title="Baby Storytime",
            date_start=datetime(2026, 4, 5, 10, 0),
            org_name="Test Library",
            location_name="Main Branch",
        )
        e2 = Event(
            title="Baby Storytime",
            date_start=datetime(2026, 4, 5, 10, 0),
            org_name="Test Library",
            location_name="Main Branch",
        )
        assert e1.uid == e2.uid

    def test_uid_changes_with_title(self):
        e1 = Event(title="Event A", date_start=datetime(2026, 4, 5), org_name="Org")
        e2 = Event(title="Event B", date_start=datetime(2026, 4, 5), org_name="Org")
        assert e1.uid != e2.uid

    def test_uid_changes_with_date(self):
        e1 = Event(title="Storytime", date_start=datetime(2026, 4, 5), org_name="Org")
        e2 = Event(title="Storytime", date_start=datetime(2026, 4, 6), org_name="Org")
        assert e1.uid != e2.uid

    def test_display_title_free(self):
        e = Event(title="Storytime", date_start=datetime(2026, 4, 5), org_name="Lib", is_free=True)
        assert e.display_title == "[FREE] Storytime"

    def test_display_title_paid(self):
        e = Event(title="Paid Event", date_start=datetime(2026, 4, 5), org_name="Org", is_free=False)
        assert e.display_title == "Paid Event"

    def test_uid_length(self):
        e = Event(title="Test", date_start=datetime(2026, 4, 5), org_name="Org")
        assert len(e.uid) == 32


# ── parse_with_selectors tests ────────────────────────────────────────────────

class TestParseWithSelectors:
    def _parse(self, html: str, config: dict = None) -> list[Event]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        cfg = config or SOURCE_CONFIG
        return parse_with_selectors(soup, cfg, cfg["name"], cfg["url"])

    def test_finds_two_events(self):
        events = self._parse(SAMPLE_HTML)
        assert len(events) == 2

    def test_event_title(self):
        events = self._parse(SAMPLE_HTML)
        assert events[0].title == "Baby Storytime"

    def test_event_is_free(self):
        events = self._parse(SAMPLE_HTML)
        assert events[0].is_free is True

    def test_event_location(self):
        events = self._parse(SAMPLE_HTML)
        assert events[0].location_name == "Main Branch"

    def test_event_tags(self):
        events = self._parse(SAMPLE_HTML)
        assert "storytime" in events[0].tags
        assert "baby" in events[0].tags

    def test_event_org_name(self):
        events = self._parse(SAMPLE_HTML)
        assert events[0].org_name == "Test Library"

    def test_empty_html_returns_no_events(self):
        events = self._parse("<html><body></body></html>")
        assert events == []

    def test_missing_date_skips_card(self):
        html = """<div class="event-card">
            <h2 class="event-title">No Date Event</h2>
        </div>"""
        events = self._parse(html)
        assert events == []


# ── HtmlScraper tests ─────────────────────────────────────────────────────────

class TestHtmlScraper:
    def test_scrape_returns_events(self):
        scraper = HtmlScraper(SETTINGS)
        with patch.object(scraper, "fetch", return_value=SAMPLE_HTML):
            events = scraper.scrape(SOURCE_CONFIG)
        assert len(events) == 2

    def test_scrape_handles_fetch_error(self):
        scraper = HtmlScraper(SETTINGS)
        with patch.object(scraper, "fetch", side_effect=Exception("Connection refused")):
            with pytest.raises(Exception, match="Connection refused"):
                scraper.scrape(SOURCE_CONFIG)

    def test_parse_returns_event_objects(self):
        scraper = HtmlScraper(SETTINGS)
        events = scraper.parse(SAMPLE_HTML, SOURCE_CONFIG)
        assert all(isinstance(e, Event) for e in events)


# ── IcalScraper tests ─────────────────────────────────────────────────────────

class TestIcalScraper:
    def test_parses_vevent(self):
        scraper = IcalScraper(SETTINGS)
        cfg = {**SOURCE_CONFIG, "name": "Test iCal Source"}
        with patch.object(scraper, "fetch", return_value=SAMPLE_ICAL):
            events = scraper.scrape(cfg)
        titles = [e.title for e in events]
        assert "Baby Yoga Class" in titles

    def test_parses_location(self):
        scraper = IcalScraper(SETTINGS)
        cfg = {**SOURCE_CONFIG, "name": "Test iCal Source"}
        with patch.object(scraper, "fetch", return_value=SAMPLE_ICAL):
            events = scraper.scrape(cfg)
        yoga = next(e for e in events if e.title == "Baby Yoga Class")
        assert "Lincoln Park" in yoga.location_name

    def test_is_free_from_description(self):
        scraper = IcalScraper(SETTINGS)
        cfg = {**SOURCE_CONFIG, "name": "Test iCal Source"}
        with patch.object(scraper, "fetch", return_value=SAMPLE_ICAL):
            events = scraper.scrape(cfg)
        yoga = next(e for e in events if e.title == "Baby Yoga Class")
        assert yoga.is_free is True

    def test_invalid_ical_returns_empty(self):
        scraper = IcalScraper(SETTINGS)
        with patch.object(scraper, "fetch", return_value="NOT VALID ICAL CONTENT"):
            events = scraper.scrape(SOURCE_CONFIG)
        assert events == []


# ── _infer_free tests ─────────────────────────────────────────────────────────

class TestInferFree:
    def test_free_in_cost_hint(self):
        assert _infer_free("free", "", "") is True

    def test_free_in_description(self):
        assert _infer_free("", "", "This event is free!") is True

    def test_dollar_sign_overrides_free(self):
        assert _infer_free("", "Free-ish event", "Costs $5") is False

    def test_admission_required_overrides(self):
        assert _infer_free("", "Family event free day", "Admission required") is False

    def test_no_indicators_returns_false(self):
        assert _infer_free("", "Some Event", "Bring your family") is False

    def test_complimentary_is_free(self):
        assert _infer_free("", "Complimentary admission", "") is True
