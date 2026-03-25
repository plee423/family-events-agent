"""Scraper for Eventbrite organization-based events API.

Fetches events from a configured list of Chicago family/baby/toddler organizers.
Requires EVENTBRITE_TOKEN environment variable (free Eventbrite developer account).

API docs: https://www.eventbrite.com/platform/api#/reference/organization/list-events-by-organization/
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import requests
from dateutil import parser as dateutil_parser
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event, _infer_free

logger = logging.getLogger(__name__)


class EventbriteScraper(BaseScraper):
    """
    Fetches family events from Eventbrite using the organization-based API.

    Calls GET /v3/organizers/{id}/events/ for each org_id in the source config.
    The deprecated /v3/events/search/ endpoint (shut down Feb 2020) is no longer used.
    Note: /v3/organizations/ is an account-management path (requires elevated auth);
          /v3/organizers/ is the public-facing path for event creators — use that.

    Required env var: EVENTBRITE_TOKEN

    Configure in sources.yaml:
        scraper: eventbrite
        org_ids:                          # list of Eventbrite organization IDs
          - "14498519145"                 # Weissbluth Pediatrics
          - "31435451531"                 # FAME Center
          ...
        max_pages: 5                      # per org (default 5, 50 events/page = 250 max)
        tags: [...]
        age_hint: "0-60 months"
    """

    API_BASE = "https://www.eventbriteapi.com/v3"

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.token = os.environ.get("EVENTBRITE_TOKEN", "")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Authorization": f"Bearer {self.token}",
        })

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _get(self, url: str, params: dict) -> dict:
        time.sleep(self.request_delay)
        resp = self.session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def fetch(self, url: str) -> str:
        return ""

    def parse(self, content: str, source_config: dict) -> list[Event]:
        return []

    def scrape(self, source_config: dict) -> list[Event]:
        if not self.token:
            self.logger.warning(
                "EVENTBRITE_TOKEN not set — skipping Eventbrite source. "
                "Get a free token at eventbrite.com/platform"
            )
            return []

        org_ids: list[str] = source_config.get("org_ids", [])
        if not org_ids:
            self.logger.warning("No org_ids configured for Eventbrite source — skipping")
            return []

        source_name = source_config.get("name", "Eventbrite")
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "")

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        all_events: list[Event] = []

        for org_id in org_ids:
            org_events = self._fetch_org_events(
                org_id=str(org_id),
                source_name=source_name,
                tags=tags,
                age_hint=age_hint,
                start_after=now_utc,
            )
            all_events.extend(org_events)
            self.logger.info("  Org %s: %d upcoming events", org_id, len(org_events))

        self.logger.info("  %s: found %d events across %d orgs", source_name, len(all_events), len(org_ids))
        return all_events

    def _fetch_org_events(
        self,
        org_id: str,
        source_name: str,
        tags: list,
        age_hint: str,
        start_after: str,
    ) -> list[Event]:
        """Fetch upcoming events for a single Eventbrite organizer.

        The /v3/organizers/{id}/events/ endpoint only supports the 'expand' param.
        It does not accept status, page_size, or date-range filters (all return 400).
        Default page size is 50. We filter past events in Python via start_after.
        """
        params = {"expand": "venue,ticket_classes"}

        events: list[Event] = []

        try:
            data = self._get(
                f"{self.API_BASE}/organizers/{org_id}/events/",
                params,
            )
        except Exception as exc:
            self.logger.error("Eventbrite org %s fetch failed: %s", org_id, exc)
            return events

        raw_items = data.get("events", [])
        self.logger.info("  Org %s: API returned %d total events (page 1)", org_id, len(raw_items))
        for item in raw_items:
            event = self._parse_event(item, source_name, tags, age_hint, start_after)
            if event:
                events.append(event)

        past_dropped = len(raw_items) - len(events)
        if past_dropped:
            self.logger.info(
                "  Org %s: dropped %d past events, %d upcoming remain",
                org_id, past_dropped, len(events),
            )

        if data.get("pagination", {}).get("has_more_items"):
            self.logger.warning(
                "Eventbrite org %s has >50 events — only first 50 fetched", org_id
            )

        return events

    def _parse_event(
        self, item: dict, org_name: str, tags: list, age_hint: str,
        start_after: str | None = None,
    ) -> Event | None:
        title = (item.get("name") or {}).get("text", "").strip()
        if not title:
            return None

        # Dates
        start = item.get("start") or {}
        end = item.get("end") or {}
        start_utc = start.get("utc", "")
        end_utc = end.get("utc", "")

        if not start_utc:
            return None
        try:
            date_start = dateutil_parser.parse(start_utc)
            date_end = dateutil_parser.parse(end_utc) if end_utc else None
        except Exception:
            return None

        # Client-side future filter (endpoint doesn't support date range params)
        if start_after:
            try:
                cutoff = dateutil_parser.parse(start_after)
                if date_start < cutoff:
                    return None
            except Exception:
                pass

        # Venue
        venue = item.get("venue") or {}
        location_name = (venue.get("name") or "").strip()
        addr = venue.get("address") or {}
        addr_parts = [
            addr.get("address_1", ""),
            addr.get("city", ""),
            addr.get("region", ""),
            addr.get("postal_code", ""),
        ]
        location_address = ", ".join(p for p in addr_parts if p)

        # Lat/lng from venue if available
        location_lat = None
        location_lng = None
        try:
            if venue.get("latitude"):
                location_lat = float(venue["latitude"])
                location_lng = float(venue["longitude"])
        except (TypeError, ValueError):
            pass

        # Description
        description = (item.get("description") or {}).get("text", "")[:500]

        # Cost — check ticket classes then fall back to is_free flag
        is_free_flag = item.get("is_free", False)
        ticket_classes = item.get("ticket_classes") or []
        min_cost = None
        for tc in ticket_classes:
            cost_val = tc.get("cost") or {}
            major = cost_val.get("major_value")
            if major is not None:
                try:
                    v = float(major)
                    if min_cost is None or v < min_cost:
                        min_cost = v
                except (TypeError, ValueError):
                    pass

        if is_free_flag or min_cost == 0:
            cost_str = "free"
            is_free = True
        elif min_cost is not None:
            cost_str = f"${min_cost:.0f}+"
            is_free = False
        else:
            cost_str = ""
            is_free = _infer_free("", title, description)

        url = item.get("url", "")

        return Event(
            title=title,
            date_start=date_start,
            date_end=date_end,
            org_name=org_name,
            location_name=location_name or org_name,
            location_address=location_address,
            location_lat=location_lat,
            location_lng=location_lng,
            description=description,
            url=url,
            cost=cost_str,
            is_free=is_free,
            age_range=age_hint,
            tags=list(tags),
            source_name=org_name,
        )
