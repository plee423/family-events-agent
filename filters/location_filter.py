"""Filter events by distance from home and enrich with geocoded coordinates."""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

from scrapers.base import Event

logger = logging.getLogger(__name__)


def filter_by_location(events: list[Event], settings: dict) -> list[Event]:
    """
    1. Geocode events that have an address but no lat/lng.
    2. Compute distance from home.
    3. Filter out events beyond max_radius_miles.
    Events with no location info at all are kept (we can't exclude them fairly).
    """
    loc_cfg = settings.get("location", {})
    home_lat = loc_cfg.get("home_lat")
    home_lng = loc_cfg.get("home_lng")
    max_radius = loc_cfg.get("max_radius_miles", 10)
    city = loc_cfg.get("city", "")
    state = loc_cfg.get("state", "")

    if home_lat is None or home_lng is None:
        logger.warning("No home coordinates configured — skipping location filter")
        return events

    geocoder = _build_geocoder(city, state)

    kept: list[Event] = []
    for event in events:
        # If no address info at all, keep the event (benefit of the doubt)
        if not event.location_name and not event.location_address:
            kept.append(event)
            continue

        # Try to geocode if we have an address but no coords
        if event.location_lat is None and event.location_address:
            lat, lng = _geocode(event.location_address, city, state, geocoder)
            if lat is not None:
                event.location_lat = lat
                event.location_lng = lng

        # Fall back to org name + city if still no coords
        if event.location_lat is None and event.location_name:
            query = f"{event.location_name}, {city}, {state}"
            lat, lng = _geocode(query, city, state, geocoder)
            if lat is not None:
                event.location_lat = lat
                event.location_lng = lng

        # If still no coords, keep the event
        if event.location_lat is None:
            kept.append(event)
            continue

        dist = _haversine(home_lat, home_lng, event.location_lat, event.location_lng)
        event.distance_miles = round(dist, 1)

        if dist <= max_radius:
            kept.append(event)
        else:
            logger.debug(
                "  REJECT (%.1f mi > %.1f mi radius): %s @ %s",
                dist, max_radius, event.title, event.location_name,
            )

    logger.info("Location filter: %d → %d events", len(events), len(kept))
    return kept


def _build_geocoder(city: str, state: str):
    """Build a Nominatim geocoder with a custom user-agent."""
    try:
        from geopy.geocoders import Nominatim
        from geopy.extra.rate_limiter import RateLimiter

        geolocator = Nominatim(user_agent="FamilyEventsAgent/1.0")
        # RateLimiter enforces ≥1 second between requests (Nominatim ToS)
        return RateLimiter(geolocator.geocode, min_delay_seconds=1.0)
    except ImportError:
        logger.warning("geopy not installed — location filtering disabled")
        return None


def _geocode(
    address: str, city: str, state: str, geocoder
) -> tuple[Optional[float], Optional[float]]:
    if geocoder is None:
        return None, None
    try:
        result = geocoder(f"{address}, {city}, {state}", timeout=10)
        if result:
            return result.latitude, result.longitude
    except Exception as exc:
        logger.debug("Geocode failed for %r: %s", address, exc)
    return None, None


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return distance in miles between two lat/lng points."""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
