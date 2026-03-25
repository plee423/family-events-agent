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
        max_pages = int(source_config.get("max_pages", 5))

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        all_events: list[Event] = []

        for org_id in org_ids:
            org_events = self._fetch_org_events(
                org_id=str(org_id),
                source_name=source_name,
                tags=tags,
                age_hint=age_hint,
                start_after=now_utc,
                max_pages=max_pages,
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
        max_pages: int = 5,
    ) -> list[Event]:
        """Fetch upcoming events for a single Eventbrite organizer.

        The /v3/organizers/{id}/events/ endpoint returns events in ascending date order
        (oldest first), including past events.  An org with many past events will fill
        the entire first page with past events, so we must paginate using the
        continuation token until we hit future events or exhaust max_pages.
        """
        params = {"expand": "venue,ticket_classes"}

        events: list[Event] = []
        total_raw = 0

        for page_num in range(1, max_pages + 1):
            try:
                data = self._get(
                    f"{self.API_BASE}/organizers/{org_id}/events/",
                    params,
                )
            except Exception as exc:
                self.logger.error("Eventbrite org %s page %d fetch failed: %s", org_id, page_num, exc)
                break

            raw_items = data.get("events", [])
            total_raw += len(raw_items)
            self.logger.info(
                "  Org %s page %d: %d events from API", org_id, page_num, len(raw_items)
            )

            if not raw_items:
                break

            for item in raw_items:
                event = self._parse_event(item, source_name, tags, age_hint, start_after)
                if event:
                    events.append(event)

            pagination = data.get("pagination", {})
            if not pagination.get("has_more_items"):
                break

            continuation = pagination.get("continuation")
            if not continuation:
                break
            # Pass continuation token on next request
            params = {"expand": "venue,ticket_classes", "continuation": continuation}

        past_dropped = total_raw - len(events)
        self.logger.info(
            "  Org %s: %d total fetched, %d past dropped, %d upcoming",
            org_id, total_raw, past_dropped, len(events),
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

        # Virtual / online event detection.
        # Eventbrite sets is_online_event=True for events with no physical venue.
        # Also catch the "0.0"/"0" lat/lng that Eventbrite uses for online events.
        is_online = bool(item.get("is_online_event") or item.get("online_event"))
        try:
            lat_raw = venue.get("latitude")
            lng_raw = venue.get("longitude")
            if lat_raw and lng_raw and float(lat_raw) == 0.0 and float(lng_raw) == 0.0:
                is_online = True
        except (TypeError, ValueError):
            pass

        neighborhood = "Virtual" if is_online else ""

        # Lat/lng — leave None for virtual events so location_filter skips them.
        location_lat = None
        location_lng = None
        if not is_online:
            try:
                lat_raw = venue.get("latitude")
                lng_raw = venue.get("longitude")
                if lat_raw and lng_raw:
                    lat_f = float(lat_raw)
                    lng_f = float(lng_raw)
                    if lat_f != 0.0 and lng_f != 0.0:
                        location_lat = lat_f
                        location_lng = lng_f
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
            neighborhood=neighborhood,
        )
