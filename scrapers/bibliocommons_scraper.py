"""
Dedicated scraper for Bibliocommons library event APIs.
Used by Chicago Public Library (and optionally Irvine PL which also uses Bibliocommons).

API base: https://gateway.bibliocommons.com/v2/libraries/{library_id}/events
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from html import unescape
import re

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event

logger = logging.getLogger(__name__)

# Accurate coordinates for every CPL branch, sourced from the City of Chicago
# Open Data portal (dataset x8fc-8rcq).  The Bibliocommons /branches API returns
# no address data, so without this table every branch falls back to geocoding
# just its name — which causes Nominatim to return wrong results (e.g.
# "Blackstone, Chicago, IL" → Blackstone Hotel in The Loop instead of the
# Blackstone Branch Library in Hyde Park).
#
# Keys are the branch names exactly as returned by the Bibliocommons API.
# Values are (lat, lng, full_address).
_CPL_BRANCH_COORDS: dict[str, tuple[float, float, str]] = {
    "Albany Park":                  (41.9756, -87.7136, "3401 W. Foster Ave., Chicago, IL 60625"),
    "Altgeld":                      (41.6572, -87.5988, "955 E. 131st St., Chicago, IL 60827"),
    "Archer Heights":               (41.8011, -87.7265, "5055 S. Archer Ave., Chicago, IL 60632"),
    "Austin":                       (41.8892, -87.7658, "5615 W. Race Ave., Chicago, IL 60644"),
    "Austin-Irving":                (41.9531, -87.7793, "6100 W. Irving Park Rd., Chicago, IL 60634"),
    "Avalon":                       (41.7464, -87.5860, "8148 S. Stony Island Ave., Chicago, IL 60617"),
    "Back of the Yards":            (41.8084, -87.6776, "2111 W. 47th St., Chicago, IL 60609"),
    "Beverly":                      (41.7212, -87.6721, "1962 W. 95th St., Chicago, IL 60643"),
    "Bezazian":                     (41.9716, -87.6610, "1226 W. Ainslie St., Chicago, IL 60640"),
    "Blackstone":                   (41.8055, -87.5892, "4904 S. Lake Park Ave., Chicago, IL 60615"),
    "Brainerd":                     (41.7324, -87.6577, "1350 W. 89th St., Chicago, IL 60620"),
    "Brighton Park":                (41.8152, -87.7027, "4314 S. Archer Ave., Chicago, IL 60632"),
    "Bucktown-Wicker Park":         (41.9124, -87.6803, "1701 N. Milwaukee Ave., Chicago, IL 60647"),
    "Budlong Woods":                (41.9837, -87.6963, "5630 N. Lincoln Ave., Chicago, IL 60659"),
    "Canaryville":                  (41.8163, -87.6426, "642 W. 43rd St., Chicago, IL 60609"),
    "Chicago Bee":                  (41.8282, -87.6263, "3647 S. State St., Chicago, IL 60609"),
    "Chicago Lawn":                 (41.7820, -87.7034, "6120 S. Kedzie Ave., Chicago, IL 60629"),
    "Chinatown":                    (41.8541, -87.6320, "2100 S. Wentworth Ave., Chicago, IL 60616"),
    "Clearing":                     (41.7767, -87.7822, "6423 W. 63rd Pl., Chicago, IL 60638"),
    "Coleman":                      (41.7803, -87.6071, "731 E. 63rd St., Chicago, IL 60637"),
    "Daley Richard J.-Bridgeport":  (41.8328, -87.6463, "3400 S. Halsted St., Chicago, IL 60608"),
    "Daley Richard M.-W Humboldt":  (41.8947, -87.7064, "733 N. Kedzie Ave., Chicago, IL 60612"),
    "Douglass":                     (41.8644, -87.7102, "3353 W. 13th St., Chicago, IL 60623"),
    "Dunning":                      (41.9432, -87.8140, "7455 W. Cornelia Ave., Chicago, IL 60634"),
    "Edgebrook":                    (41.9972, -87.7621, "5331 W. Devon Ave., Chicago, IL 60646"),
    "Edgewater":                    (41.9910, -87.6604, "6000 N. Broadway St., Chicago, IL 60660"),
    "Gage Park":                    (41.7936, -87.6941, "2807 W. 55th St., Chicago, IL 60632"),
    "Galewood-Mont Clare":          (41.9210, -87.7979, "6871 W. Belden Ave., Chicago, IL 60707"),
    "Garfield Ridge":               (41.7929, -87.7801, "6348 S. Archer Ave., Chicago, IL 60638"),
    "Greater Grand Crossing":       (41.7624, -87.6005, "1000 E. 73rd St., Chicago, IL 60619"),
    "Hall":                         (41.8074, -87.6226, "4801 S. Michigan Ave., Chicago, IL 60615"),
    "Harold Washington Library Center": (41.8769, -87.6278, "400 S. State St., Chicago, IL 60605"),
    "Hegewisch":                    (41.6593, -87.5488, "3048 E. 130th St., Chicago, IL 60633"),
    "Humboldt Park":                (41.9103, -87.7055, "1605 N. Troy St., Chicago, IL 60647"),
    "Independence":                 (41.9541, -87.7200, "4024 N. Elston Ave., Chicago, IL 60618"),
    "Jefferson Park":               (41.9675, -87.7618, "5363 W. Lawrence Ave., Chicago, IL 60630"),
    "Jeffery Manor":                (41.7134, -87.5657, "2401 E. 100th St., Chicago, IL 60617"),
    "Kelly":                        (41.7820, -87.6374, "6151 S. Normal Blvd., Chicago, IL 60621"),
    "King":                         (41.8318, -87.6175, "3436 S. King Dr., Chicago, IL 60616"),
    "Legler Regional":              (41.8793, -87.7255, "115 S. Pulaski Rd., Chicago, IL 60624"),
    "Lincoln Belmont":              (41.9405, -87.6710, "1659 W. Melrose St., Chicago, IL 60657"),
    "Lincoln Park":                 (41.9254, -87.6581, "1150 W. Fullerton Ave., Chicago, IL 60614"),
    "Little Italy":                 (41.8695, -87.6607, "1336 W. Taylor St., Chicago, IL 60607"),
    "Little Village":               (41.8496, -87.7050, "2311 S. Kedzie Ave., Chicago, IL 60623"),
    "Logan Square":                 (41.9249, -87.7035, "3030 W. Fullerton Ave., Chicago, IL 60647"),
    "Lozano":                       (41.8576, -87.6612, "1805 S. Loomis St., Chicago, IL 60608"),
    "Manning":                      (41.8811, -87.6792, "6 S. Hoyne Ave., Chicago, IL 60612"),
    "Mayfair":                      (41.9682, -87.7380, "4400 W. Lawrence Ave., Chicago, IL 60630"),
    "McKinley Park":                (41.8303, -87.6735, "1915 W. 35th St., Chicago, IL 60609"),
    "Merlo":                        (41.9401, -87.6460, "644 W. Belmont Ave., Chicago, IL 60657"),
    "Mount Greenwood":              (41.6930, -87.7010, "11010 S. Kedzie Ave., Chicago, IL 60655"),
    "Near North":                   (41.9039, -87.6366, "310 W. Division St., Chicago, IL 60610"),
    "North Austin":                 (41.9094, -87.7690, "5724 W. North Ave., Chicago, IL 60639"),
    "North Pulaski":                (41.9099, -87.7338, "4300 W. North Ave., Chicago, IL 60639"),
    "Northtown":                    (42.0051, -87.6902, "6800 N. Western Ave., Chicago, IL 60645"),
    "Oriole Park":                  (41.9781, -87.8142, "7454 W. Balmoral Ave., Chicago, IL 60656"),
    "Portage-Cragin":               (41.9388, -87.7547, "5108 W. Belmont Ave., Chicago, IL 60641"),
    "Pullman":                      (41.6944, -87.6181, "11001 S. Indiana Ave., Chicago, IL 60628"),
    "Roden":                        (41.9920, -87.7982, "6083 N. Northwest Hwy., Chicago, IL 60631"),
    "Rogers Park":                  (42.0068, -87.6733, "6907 N. Clark St., Chicago, IL 60626"),
    "Scottsdale":                   (41.7493, -87.7244, "4101 W. 79th St., Chicago, IL 60652"),
    "Sherman Park":                 (41.7948, -87.6550, "5440 S. Racine Ave., Chicago, IL 60609"),
    "South Chicago":                (41.7303, -87.5497, "9055 S. Houston Ave., Chicago, IL 60617"),
    "South Shore":                  (41.7625, -87.5639, "2505 E. 73rd St., Chicago, IL 60649"),
    "Sulzer Regional":              (41.9630, -87.6847, "4455 N. Lincoln Ave., Chicago, IL 60625"),
    "Thurgood Marshall":            (41.7573, -87.6541, "7506 S. Racine Ave., Chicago, IL 60620"),
    "Toman":                        (41.8421, -87.7246, "2708 S. Pulaski Rd., Chicago, IL 60623"),
    "Uptown":                       (41.9583, -87.6542, "929 W. Buena Ave., Chicago, IL 60613"),
    "Vodak-East Side":              (41.7028, -87.6143, "3710 E. 106th St., Chicago, IL 60617"),
    "Walker":                       (41.6920, -87.6739, "11071 S. Hoyne Ave., Chicago, IL 60643"),
    "Water Works":                  (41.8975, -87.6234, "163 E. Pearson St., Chicago, IL 60611"),
    "West Belmont":                 (41.9367, -87.7860, "3104 N. Narragansett Ave., Chicago, IL 60634"),
    "West Chicago Avenue":          (41.8951, -87.7481, "4856 W. Chicago Ave., Chicago, IL 60651"),
    "West Englewood":               (41.7793, -87.6684, "1745 W. 63rd St., Chicago, IL 60621"),
    "West Lawn":                    (41.7788, -87.7237, "4020 W. 63rd St., Chicago, IL 60636"),
    "West Loop":                    (41.8837, -87.6546, "122 N. Aberdeen St., Chicago, IL 60607"),
    "West Pullman":                 (41.6779, -87.6432, "830 W. 119th St., Chicago, IL 60643"),
    "West Town":                    (41.8959, -87.6683, "1625 W. Chicago Ave., Chicago, IL 60622"),
    "Whitney M. Young Jr.":         (41.7510, -87.6150, "415 E. 79th St., Chicago, IL 60619"),
    "Woodson Regional":             (41.7207, -87.6430, "9525 S. Halsted St., Chicago, IL 60628"),
    "Wrightwood-Ashburn":           (41.7380, -87.7022, "8530 S. Kedzie Ave., Chicago, IL 60652"),
}

# Stable CPL audience IDs (verified from API response 2026-03-22)
_BABY_AUDIENCE_IDS = {
    "53f250153860d1000000000d",  # Babies: 0 to 18 months
    "53f250153860d1000000000e",  # Toddlers: 18 to 36 months
    "53f250153860d1000000000f",  # Preschoolers: 3 to 5 years
}
_ADULT_AUDIENCE_ID = "53f250153860d10000000012"  # Adults: 18 and up

# Audience ID → age_range string
_AUDIENCE_AGE_MAP = {
    "53f250153860d1000000000d": "0-18 months",
    "53f250153860d1000000000e": "18-36 months",
    "53f250153860d1000000000f": "36-60 months",
    "53f250153860d10000000012": "adults",
}


class BibliocommunesScraper(BaseScraper):
    """
    Fetches events from the Bibliocommons JSON gateway API.

    Required source config keys:
        library_id: "chipublib"  (the subdomain on bibliocommons.com)
        audiences: "babies_and_toddlers"  (comma-separated, optional)
        types: "storytime"  (comma-separated, optional)
        branch_filter: ["Near North", "Harold Washington"]  (optional, filter to specific branches)
    """

    BASE = "https://gateway.bibliocommons.com/v2/libraries/{library_id}"

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        })
        self._branch_cache: dict[str, str] = {}  # id → name

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _get(self, url: str, params: dict = None) -> dict:
        time.sleep(0.25)  # API calls can be faster than HTML scraping
        resp = self.session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _fetch_branches(self, library_id: str) -> dict[str, dict]:
        """Return {branch_id: {name, address}} mapping."""
        if self._branch_cache:
            return self._branch_cache
        url = self.BASE.format(library_id=library_id) + "/branches"
        try:
            data = self._get(url)
            branches = data.get("entities", {}).get("branches", {})
            for k, v in branches.items():
                name = v.get("name", k)
                # Build address string from structured fields if available
                addr = v.get("physicalAddress") or v.get("address") or {}
                if isinstance(addr, dict):
                    parts = [
                        addr.get("street1", ""),
                        addr.get("city", ""),
                        addr.get("region", ""),
                        addr.get("postalCode", ""),
                    ]
                    address_str = ", ".join(p for p in parts if p)
                else:
                    address_str = str(addr) if addr else ""
                self._branch_cache[k] = {"name": name, "address": address_str}
        except Exception as exc:
            logger.warning("Could not fetch branch data: %s", exc)
        return self._branch_cache

    def fetch(self, url: str) -> str:
        # Not used directly — we override scrape() instead
        return ""

    def parse(self, content: str, source_config: dict) -> list[Event]:
        # Not used directly
        return []

    def scrape(self, source_config: dict) -> list[Event]:
        """Override: use the API directly instead of fetch+parse."""
        library_id = source_config.get("library_id", "chipublib")
        audiences = source_config.get("audiences", "babies_and_toddlers")
        event_types = source_config.get("event_types", "")
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "0-60 months")
        org_name = source_config.get("name", "Chicago Public Library")
        branch_filter = source_config.get("branch_filter", [])  # [] = all branches

        base_url = self.BASE.format(library_id=library_id) + "/events"
        branches = self._fetch_branches(library_id)

        # NOTE: CPL API does not sort by date and ignores audience/type filters server-side.
        # We fetch up to max_pages pages and rely on the downstream date+age filters.
        # At 10 events/page, 50 pages = 500 events — a solid statistical sample of
        # upcoming events across all 80+ branches.
        max_pages = source_config.get("max_pages", 50)

        params = {"page": 1}
        if audiences:
            params["audiences"] = audiences
        if event_types:
            params["types"] = event_types

        all_events: list[Event] = []
        page = 1
        total_pages = 1

        while page <= total_pages and page <= max_pages:
            params["page"] = page
            try:
                data = self._get(base_url, params)
            except Exception as exc:
                logger.error("API fetch failed page %d for %s: %s", page, org_name, exc)
                break

            pagination = data.get("events", {}).get("pagination", {})
            total_pages = pagination.get("pages", 1)
            item_ids = data.get("events", {}).get("items", [])
            events_map = data.get("entities", {}).get("events", {})

            for event_id in item_ids:
                event_data = events_map.get(event_id)
                if not event_data:
                    continue
                event = self._parse_event(event_data, org_name, tags, age_hint, branches, library_id)
                if event:
                    all_events.append(event)

            page += 1

        # Apply branch filter if specified
        if branch_filter:
            bf_lower = [b.lower() for b in branch_filter]
            all_events = [
                e for e in all_events
                if any(b in e.location_name.lower() for b in bf_lower)
            ]
            logger.info("  Branch filter applied: %d events kept", len(all_events))

        self.logger.info("  %s: found %d events", org_name, len(all_events))
        return all_events

    def _parse_event(
        self, data: dict, org_name: str, tags: list, age_hint: str,
        branches: dict, library_id: str = "chipublib"
    ) -> Event | None:
        defn = data.get("definition", {})

        title = defn.get("title", "").strip()
        if not title or defn.get("isCancelled"):
            return None

        # Audience filtering: skip events that are only for adults
        audience_ids = set(defn.get("audienceIds", []))
        if audience_ids:
            only_adult = audience_ids == {_ADULT_AUDIENCE_ID}
            if only_adult:
                return None  # skip pure adult events
            age_range = _audiences_to_age_range(audience_ids) or age_hint
        else:
            age_range = age_hint  # no audience info → use source-level hint

        # Dates
        start_str = defn.get("start", "")
        end_str = defn.get("end", "")
        if not start_str:
            return None
        try:
            date_start = datetime.fromisoformat(start_str)
            date_end = datetime.fromisoformat(end_str) if end_str else None
        except ValueError:
            return None

        # Branch / location — branches dict is now {id: {name, address}}
        branch_id = defn.get("branchLocationId", "")
        branch_info = branches.get(branch_id, {})
        branch_name = branch_info.get("name", branch_id) if isinstance(branch_info, dict) else str(branch_info)
        location_name = f"{branch_name}" if branch_name else org_name

        # Look up accurate coords from the pre-built table (Bibliocommons API
        # returns no address data, so bare branch names geocode incorrectly).
        branch_coords = _CPL_BRANCH_COORDS.get(branch_name)
        if branch_coords:
            location_lat, location_lng, location_address = branch_coords
        else:
            location_lat, location_lng = None, None
            location_address = branch_info.get("address", "") if isinstance(branch_info, dict) else ""

        # Description — strip HTML tags
        raw_desc = defn.get("description", "")
        description = _strip_html(raw_desc)

        # URL — built from library_id so Irvine/OCPL/etc. get correct links
        url = f"https://{library_id}.bibliocommons.com/events/{data['id']}"

        return Event(
            title=title,
            date_start=date_start,
            date_end=date_end,
            org_name=org_name,
            location_name=location_name,
            location_address=location_address,
            location_lat=location_lat,
            location_lng=location_lng,
            description=description[:500],
            url=url,
            cost="free",
            is_free=True,
            age_range=age_range,
            tags=list(tags),
            source_name=org_name,
        )


def _audiences_to_age_range(audience_ids: set) -> str:
    """Convert a set of audience IDs to a human-readable age range string."""
    ranges = [_AUDIENCE_AGE_MAP[aid] for aid in audience_ids if aid in _AUDIENCE_AGE_MAP and aid != _ADULT_AUDIENCE_ID]
    if not ranges:
        return ""
    # Build a combined range: take min of lowers and max of uppers
    import re
    months = []
    for r in ranges:
        m = re.match(r"(\d+)-(\d+)\s*(months?|years?)", r)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if "year" in m.group(3):
                lo *= 12; hi *= 12
            months.append((lo, hi))
    if not months:
        return ", ".join(ranges)
    lo = min(m[0] for m in months)
    hi = max(m[1] for m in months)
    return f"{lo}-{hi} months"


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
