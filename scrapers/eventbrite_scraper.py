"""Scraper for Eventbrite public events API.

Searches for family/baby/toddler events near a configured location.
Requires EVENTBRITE_TOKEN environment variable (free Eventbrite developer account).

API docs: https://www.eventbrite.com/platform/api#/reference/event/search/
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

# Eventbrite category IDs relevant to family events
# 1=Business, 10=Music, 11=Film, 12=Arts, 13=Fashion, 14=Health,
# 15=Sports, 16=Travel, 17=Food, 18=Charity, 19=Politics,
# 99=Other, 100=Science, 110=Holiday, 111=Family, 112=Education, 113=Seasonal
_FAMILY_CATEGORY_IDS = "111,112"  # Family & Education

_SEARCH_KEYWORDS = (
    "baby toddler storytime family kids infant preschool children lapsit"
)


class EventbriteScraper(BaseScraper):
    """
    Fetches family events from the Eventbrite public search API.

    Required env var: EVENTBRITE_TOKEN

    Configure in sources.yaml:
        scraper: eventbrite
        # all other fields are optional overrides
        keywords: "baby toddler storytime"     # default: see _SEARCH_KEYWORDS
        radius: "10mi"                          # default from settings max_radius_miles
        max_pages: 5                            # default 5 (50 events/page = 250 max)
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

        loc_cfg = self.settings.get("location", {})
        home_lat = loc_cfg.get("home_lat")
        home_lng = loc_cfg.get("home_lng")
        max_radius = loc_cfg.get("max_radius_miles", 10)

        if home_lat is None or home_lng is None:
            self.logger.warning("No home coordinates in settings — skipping Eventbrite")
            return []

        org_name = source_config.get("name", "Eventbrite")
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "")
        keywords = source_config.get("keywords", _SEARCH_KEYWORDS)
        radius = source_config.get("radius", f"{max_radius}mi")
        max_pages = int(source_config.get("max_pages", 5))

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "q": keywords,
            "location.latitude": home_lat,
            "location.longitude": home_lng,
            "location.within": radius,
            "categories": _FAMILY_CATEGORY_IDS,
            "start_date.range_start": now_utc,
            "expand": "venue,ticket_classes",
            "page_size": 50,
            "page": 1,
        }

        all_events: list[Event] = []
        page = 1

        while page <= max_pages:
            params["page"] = page
            try:
                data = self._get(f"{self.API_BASE}/events/search/", params)
            except Exception as exc:
                self.logger.error("Eventbrite API fetch failed page %d: %s", page, exc)
                break

            for item in data.get("events", []):
                event = self._parse_event(item, org_name, tags, age_hint)
                if event:
                    all_events.append(event)

            pagination = data.get("pagination", {})
            if not pagination.get("has_more_items", False):
                break
            page += 1

        self.logger.info("  %s: found %d events", org_name, len(all_events))
        return all_events

    def _parse_event(
        self, item: dict, org_name: str, tags: list, age_hint: str
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

        # Cost — check ticket classes
        is_free = item.get("is_free", False)
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

        if is_free or min_cost == 0:
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
