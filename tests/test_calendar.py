"""Tests for the .ics calendar generator."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.base import Event
from calendar_gen.ics_builder import build_ics, _build_vevent, _localize
import pytz


# ── Fixtures ───────────────────────────────────────────────────────────────────

SETTINGS = {
    "child": {"name": "Baby", "birth_date": "2025-03-01"},
    "location": {
        "city": "Chicago",
        "state": "IL",
        "timezone": "America/Chicago",
        "home_lat": 41.8827,
        "home_lng": -87.6233,
    },
    "preferences": {
        "include_free_only": False,
        "highlight_free": True,
        "days_ahead": 30,
    },
    "output": {
        "filename_template": "test_events_{start}_{end}.ics",
        "calendar_name": "Test Family Events",
    },
}


def make_event(**kwargs) -> Event:
    defaults = dict(
        title="Baby Storytime",
        date_start=datetime(2026, 4, 5, 10, 0),
        date_end=datetime(2026, 4, 5, 11, 0),
        org_name="Chicago Public Library",
        location_name="Harold Washington Library",
        location_address="400 S State St, Chicago, IL",
        description="Free storytime for babies and toddlers.",
        url="https://chipublib.org/events/storytime",
        cost="free",
        is_free=True,
        age_range="0-24 months",
        tags=["storytime", "baby", "library"],
    )
    defaults.update(kwargs)
    return Event(**defaults)


# ── ics_builder tests ─────────────────────────────────────────────────────────

class TestBuildIcs:
    def test_generates_file(self):
        events = [make_event()]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, SETTINGS, output_dir=tmpdir)
            assert path.exists()
            assert path.suffix == ".ics"

    def test_output_is_valid_ical(self):
        events = [make_event()]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, SETTINGS, output_dir=tmpdir)
            content = path.read_bytes()
            # Must start with BEGIN:VCALENDAR
            assert b"BEGIN:VCALENDAR" in content
            assert b"END:VCALENDAR" in content

    def test_contains_event_summary(self):
        events = [make_event(title="Test Baby Event")]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, SETTINGS, output_dir=tmpdir)
            content = path.read_text(encoding="utf-8")
            assert "Test Baby Event" in content

    def test_free_event_prefixed(self):
        events = [make_event(title="Storytime", is_free=True)]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, SETTINGS, output_dir=tmpdir)
            content = path.read_text(encoding="utf-8")
            assert "[FREE]" in content

    def test_uid_present(self):
        events = [make_event()]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, SETTINGS, output_dir=tmpdir)
            content = path.read_text(encoding="utf-8")
            assert "UID:" in content

    def test_uid_stable_across_runs(self):
        """Same event imported twice should produce the same UID."""
        e = make_event()
        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = build_ics([e], SETTINGS, output_dir=tmpdir)
            path2 = build_ics([e], SETTINGS, output_dir=tmpdir)
            # Extract UIDs
            uid1 = _extract_uid(path1.read_text())
            uid2 = _extract_uid(path2.read_text())
            assert uid1 == uid2

    def test_contains_alarm(self):
        events = [make_event()]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, SETTINGS, output_dir=tmpdir)
            content = path.read_text(encoding="utf-8")
            assert "BEGIN:VALARM" in content

    def test_contains_two_alarms(self):
        events = [make_event()]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, SETTINGS, output_dir=tmpdir)
            content = path.read_text(encoding="utf-8")
            assert content.count("BEGIN:VALARM") == 2

    def test_empty_events_generates_empty_calendar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics([], SETTINGS, output_dir=tmpdir)
            content = path.read_text(encoding="utf-8")
            assert "BEGIN:VCALENDAR" in content
            assert "BEGIN:VEVENT" not in content

    def test_multiple_events(self):
        events = [
            make_event(title="Event One"),
            make_event(title="Event Two", date_start=datetime(2026, 4, 6, 10, 0)),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, SETTINGS, output_dir=tmpdir)
            content = path.read_text(encoding="utf-8")
            assert content.count("BEGIN:VEVENT") == 2

    def test_vtimezone_present(self):
        events = [make_event()]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, SETTINGS, output_dir=tmpdir)
            content = path.read_text(encoding="utf-8")
            assert "BEGIN:VTIMEZONE" in content

    def test_calname_in_output(self):
        events = [make_event()]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, SETTINGS, output_dir=tmpdir)
            content = path.read_text(encoding="utf-8")
            assert "Test Family Events" in content


# ── _build_vevent tests ───────────────────────────────────────────────────────

class TestBuildVevent:
    def setup_method(self):
        self.tz = pytz.timezone("America/Chicago")

    def test_returns_vevent(self):
        from icalendar import Event as ICalEvent
        e = make_event()
        vevent = _build_vevent(e, self.tz)
        assert isinstance(vevent, ICalEvent)

    def test_summary_truncated(self):
        long_title = "A" * 100
        e = make_event(title=long_title)
        vevent = _build_vevent(e, self.tz)
        assert len(str(vevent.get("SUMMARY"))) <= 76  # 75 + possible [FREE] indicator

    def test_default_end_time_added(self):
        e = make_event(date_end=None)
        vevent = _build_vevent(e, self.tz)
        assert vevent.get("DTEND") is not None

    def test_url_present(self):
        e = make_event(url="https://example.com/event")
        vevent = _build_vevent(e, self.tz)
        assert vevent.get("URL") is not None

    def test_categories_from_tags(self):
        e = make_event(tags=["baby", "library"])
        vevent = _build_vevent(e, self.tz)
        assert vevent.get("CATEGORIES") is not None

    def test_sequence_is_zero(self):
        e = make_event()
        vevent = _build_vevent(e, self.tz)
        assert int(vevent.get("SEQUENCE")) == 0


# ── Timezone handling ─────────────────────────────────────────────────────────

class TestTimezone:
    def test_localize_naive_datetime(self):
        tz = pytz.timezone("America/Chicago")
        dt = datetime(2026, 4, 5, 10, 0)
        result = _localize(dt, tz)
        assert result.tzinfo is not None

    def test_localize_aware_datetime_converts(self):
        tz_chicago = pytz.timezone("America/Chicago")
        tz_utc = pytz.utc
        dt_utc = tz_utc.localize(datetime(2026, 4, 5, 15, 0))  # 3pm UTC = 10am Chicago
        result = _localize(dt_utc, tz_chicago)
        assert result.hour == 10

    def test_different_timezone_in_settings(self):
        """Switching to LA timezone should work without code changes."""
        la_settings = {
            **SETTINGS,
            "location": {**SETTINGS["location"], "timezone": "America/Los_Angeles"},
        }
        events = [make_event()]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = build_ics(events, la_settings, output_dir=tmpdir)
            content = path.read_text(encoding="utf-8")
            assert "America/Los_Angeles" in content


# ── Helper ────────────────────────────────────────────────────────────────────

def _extract_uid(ical_text: str) -> str:
    for line in ical_text.splitlines():
        if line.startswith("UID:"):
            return line[4:].strip()
    return ""
