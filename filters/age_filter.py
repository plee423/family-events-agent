"""Filter events appropriate for the child's current age."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Optional

from scrapers.base import Event

logger = logging.getLogger(__name__)

# Keywords unambiguously indicating this event is for babies/toddlers.
# "family" intentionally excluded — it appears in venue branding tags (e.g. Navy Pier)
# and causes false positives for unrelated events. Use WEAK_BABY_KEYWORDS for broader terms.
BABY_KEYWORDS = {
    "baby", "infant", "toddler", "lapsit", "lap sit",
    "0-2", "0-3", "0-18", "0-24", "0-36",
    "storytime", "story time", "rhyme time",
    "baby gym", "baby yoga", "mommy and me", "daddy and me",
    "parent and me", "caregiver and me",
    "kids", "children", "little ones",
    "preschool", "pre-k",
}

# Keywords that suggest children but are weaker signals on their own.
# Used for non-children-focused sources only to avoid false positives from venue tags.
WEAK_BABY_KEYWORDS = {"family"}

# Keywords that strongly suggest the event is NOT for babies/toddlers
ADULT_KEYWORDS = {
    "adults only", "21+", "18+", "wine", "beer", "cocktail",
    "lecture for adults", "senior", "teen only",
}


def _kw_match(text: str, keywords: set[str]) -> bool:
    """Word-boundary keyword match — avoids substring false positives like '0-2' in '10-20'."""
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            return True
    return False


def filter_by_age(
    events: list[Event],
    settings: dict,
    sources: list[dict] | None = None,
) -> list[Event]:
    """
    Keep events that are appropriate for the child's current age.

    Rules (applied in order):
    1. Adult-only keywords → reject
    2. Baby/toddler keywords in title/description/tags → keep
    3. Explicit age_range that overlaps with child's age range → keep
    4a. No age info, source is children-focused (children_only=True, default) → keep
    4b. No age info, source is NOT children-focused (children_only=False) → reject
        (non-children sources like Navy Pier need an explicit positive signal)
    """
    child_cfg = settings.get("child", {})
    birth_date_str = child_cfg.get("birth_date", "")
    age_range_cfg = child_cfg.get("age_range_months", [0, 36])

    child_age_months = _compute_age_months(birth_date_str)
    if child_age_months is None:
        logger.warning("Could not determine child age from birth_date=%r; skipping age filter", birth_date_str)
        return events

    min_age, max_age = age_range_cfg[0], age_range_cfg[1]
    logger.debug(
        "Age filter: child is %d months old, showing events for %d–%d months",
        child_age_months, min_age, max_age,
    )

    # Build lookup: source name → children_only flag (default True)
    source_map = {s["name"]: s for s in (sources or [])}

    kept: list[Event] = []
    for event in events:
        text = f"{event.title} {event.description} {' '.join(event.tags)}".lower()

        # Rule 1: adult keywords → always reject
        if _kw_match(text, ADULT_KEYWORDS):
            logger.debug("  REJECT (adult keywords): %s", event.title)
            continue

        # Rule 2: baby/toddler keywords → always keep
        if _kw_match(text, BABY_KEYWORDS):
            kept.append(event)
            continue

        # Rule 3: explicit age range → keep if it overlaps, reject if it doesn't
        event_range = _parse_age_range(event.age_range)
        if event_range is not None:
            event_min, event_max = event_range
            if event_min <= max_age and event_max >= min_age:
                kept.append(event)
            else:
                logger.debug(
                    "  REJECT (age mismatch, event=%d–%d, child=%d months): %s",
                    event_min, event_max, child_age_months, event.title,
                )
            continue

        # Rule 4: no age info and no baby keywords
        source_cfg = source_map.get(event.source_name, {})
        children_only = source_cfg.get("children_only", True)

        if children_only:
            # Trusted children-focused source: "family" alone can count as a signal
            if _kw_match(text, WEAK_BABY_KEYWORDS):
                kept.append(event)
            else:
                kept.append(event)  # No info → keep (benefit of the doubt)
        else:
            # Non-children source (e.g. Navy Pier): require an explicit positive signal
            logger.debug("  REJECT (no children signal, non-children source): %s", event.title)

    logger.info("Age filter: %d → %d events", len(events), len(kept))
    return kept


def _compute_age_months(birth_date_str: str) -> Optional[int]:
    if not birth_date_str:
        return None
    try:
        bd = date.fromisoformat(birth_date_str)
        today = date.today()
        months = (today.year - bd.year) * 12 + (today.month - bd.month)
        if today.day < bd.day:
            months -= 1
        return max(0, months)
    except ValueError:
        return None




def _parse_age_range(age_range_str: str) -> Optional[tuple[int, int]]:
    """
    Parse strings like "0-24 months", "2-5 years", "all ages" into (min_months, max_months).
    Returns None if unparseable.
    """
    if not age_range_str:
        return None

    s = age_range_str.lower().strip()

    if "all ages" in s or "all-ages" in s or "family" in s:
        return (0, 120)

    # Match patterns like "0-24 months", "6-18 months"
    m = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*(month|year)", s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        unit = m.group(3)
        if "year" in unit:
            lo *= 12
            hi *= 12
        return (lo, hi)

    # Match "under X months/years"
    m = re.search(r"under\s+(\d+)\s*(month|year)", s)
    if m:
        hi = int(m.group(1))
        if "year" in m.group(2):
            hi *= 12
        return (0, hi)

    # Match "X months and up" / "X+ months"
    m = re.search(r"(\d+)\s*\+?\s*(month|year)s?\s*(and up|and older|up|\+)?", s)
    if m:
        lo = int(m.group(1))
        if "year" in m.group(2):
            lo *= 12
        return (lo, 120)

    return None
