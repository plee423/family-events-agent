"""Tests for the filter pipeline."""
from __future__ import annotations

import pytest
from datetime import datetime

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.base import Event
from filters.age_filter import filter_by_age, _compute_age_months, _parse_age_range
from filters.cost_filter import filter_by_cost
from filters.dedup_filter import deduplicate, _dedup_key, _normalize


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_event(**kwargs) -> Event:
    defaults = dict(
        title="Storytime",
        date_start=datetime(2026, 4, 5, 10, 0),
        org_name="Library",
        location_name="Main Branch",
        tags=[],
        is_free=False,
        cost="",
        age_range="",
        description="",
    )
    defaults.update(kwargs)
    return Event(**defaults)


SETTINGS = {
    "child": {
        "birth_date": "2025-03-01",
        "age_range_months": [0, 36],
    },
    "preferences": {
        "include_free_only": False,
        "highlight_free": True,
        "days_ahead": 30,
        "exclude_keywords": ["adults-only", "21+", "wine"],
    },
    "location": {
        "home_lat": 41.8827,
        "home_lng": -87.6233,
        "max_radius_miles": 10,
        "city": "Chicago",
        "state": "IL",
    },
}


# ── Age filter tests ──────────────────────────────────────────────────────────

class TestAgeFilter:
    def test_keeps_baby_keyword_events(self):
        events = [make_event(title="Baby Yoga Class", tags=["baby"])]
        result = filter_by_age(events, SETTINGS)
        assert len(result) == 1

    def test_keeps_toddler_keyword_events(self):
        events = [make_event(title="Toddler Tuesday", description="for toddlers")]
        result = filter_by_age(events, SETTINGS)
        assert len(result) == 1

    def test_rejects_adults_only(self):
        events = [make_event(title="Adults Only Paint Night", description="21+ wine event")]
        result = filter_by_age(events, SETTINGS)
        assert len(result) == 0

    def test_keeps_no_age_info(self):
        events = [make_event(title="Generic Event")]
        result = filter_by_age(events, SETTINGS)
        assert len(result) == 1

    def test_rejects_out_of_range_explicit(self):
        events = [make_event(title="Tween Art Class", age_range="8-12 years")]
        result = filter_by_age(events, SETTINGS)
        assert len(result) == 0

    def test_keeps_overlapping_age_range(self):
        events = [make_event(title="Family Fun", age_range="0-36 months")]
        result = filter_by_age(events, SETTINGS)
        assert len(result) == 1

    def test_all_ages_kept(self):
        events = [make_event(title="Concert", age_range="all ages")]
        result = filter_by_age(events, SETTINGS)
        assert len(result) == 1

    def test_storytime_in_title_kept(self):
        events = [make_event(title="Saturday Storytime")]
        result = filter_by_age(events, SETTINGS)
        assert len(result) == 1


class TestComputeAgeMonths:
    def test_roughly_correct(self):
        from datetime import date, timedelta
        birth = (date.today() - timedelta(days=365)).isoformat()
        age = _compute_age_months(birth)
        assert 11 <= age <= 13

    def test_newborn(self):
        from datetime import date
        birth = date.today().isoformat()
        age = _compute_age_months(birth)
        assert age == 0

    def test_invalid_date_returns_none(self):
        assert _compute_age_months("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert _compute_age_months("") is None


class TestParseAgeRange:
    def test_months_range(self):
        assert _parse_age_range("0-24 months") == (0, 24)

    def test_years_range_converts(self):
        lo, hi = _parse_age_range("2-5 years")
        assert lo == 24
        assert hi == 60

    def test_all_ages(self):
        lo, hi = _parse_age_range("all ages")
        assert lo == 0
        assert hi == 120

    def test_under_x_months(self):
        lo, hi = _parse_age_range("under 18 months")
        assert lo == 0
        assert hi == 18

    def test_unparseable_returns_none(self):
        assert _parse_age_range("some event") is None

    def test_empty_returns_none(self):
        assert _parse_age_range("") is None


# ── Cost filter tests ──────────────────────────────────────────────────────────

class TestCostFilter:
    def test_keeps_all_when_not_free_only(self):
        events = [make_event(is_free=False), make_event(is_free=True)]
        settings = {**SETTINGS, "preferences": {**SETTINGS["preferences"], "include_free_only": False}}
        result = filter_by_cost(events, settings)
        assert len(result) == 2

    def test_filters_paid_when_free_only(self):
        events = [
            make_event(title="Free Storytime", is_free=True, cost="free"),
            make_event(title="Paid Class", is_free=False, cost="$15"),
        ]
        settings = {**SETTINGS, "preferences": {**SETTINGS["preferences"], "include_free_only": True}}
        result = filter_by_cost(events, settings)
        assert len(result) == 1
        assert result[0].title == "Free Storytime"

    def test_highlights_free_via_description(self):
        events = [make_event(title="Event", cost="", description="Admission is free for all")]
        settings = {**SETTINGS, "preferences": {**SETTINGS["preferences"], "highlight_free": True}}
        result = filter_by_cost(events, settings)
        assert result[0].is_free is True

    def test_dollar_sign_not_marked_free(self):
        events = [make_event(title="Paid Event", cost="$10 admission")]
        settings = {**SETTINGS, "preferences": {**SETTINGS["preferences"], "highlight_free": True}}
        result = filter_by_cost(events, settings)
        assert result[0].is_free is False


# ── Dedup filter tests ────────────────────────────────────────────────────────

class TestDedup:
    def test_removes_exact_duplicate(self):
        e1 = make_event(title="Storytime", location_name="Main Branch")
        e2 = make_event(title="Storytime", location_name="Main Branch")
        result = deduplicate([e1, e2])
        assert len(result) == 1

    def test_keeps_different_events(self):
        e1 = make_event(title="Storytime A", location_name="Branch 1")
        e2 = make_event(title="Storytime B", location_name="Branch 2")
        result = deduplicate([e1, e2])
        assert len(result) == 2

    def test_keeps_different_dates(self):
        e1 = make_event(title="Storytime", date_start=datetime(2026, 4, 5))
        e2 = make_event(title="Storytime", date_start=datetime(2026, 4, 12))
        result = deduplicate([e1, e2])
        assert len(result) == 2

    def test_prefers_more_complete_event(self):
        sparse = make_event(title="Storytime", description="")
        rich = make_event(title="Storytime", description="A very detailed description here", url="https://example.com")
        result = deduplicate([sparse, rich])
        assert result[0].url == "https://example.com"

    def test_normalize_punctuation(self):
        assert _normalize("Baby's Storytime!") == _normalize("Babys Storytime")

    def test_normalize_case(self):
        assert _normalize("STORYTIME") == _normalize("storytime")

    def test_dedup_key_consistency(self):
        e = make_event(title="Event", location_name="Loc")
        assert _dedup_key(e) == _dedup_key(e)
