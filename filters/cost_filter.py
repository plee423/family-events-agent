"""Filter events by cost and flag free events."""
from __future__ import annotations

import logging

from scrapers.base import Event

logger = logging.getLogger(__name__)


def filter_by_cost(events: list[Event], settings: dict) -> list[Event]:
    """
    If include_free_only is True: remove paid events.
    Otherwise: keep all events but mark free ones with is_free=True.
    The display_title property will prepend "[FREE]" for free events.
    """
    prefs = settings.get("preferences", {})
    include_free_only = prefs.get("include_free_only", False)
    highlight_free = prefs.get("highlight_free", True)

    if highlight_free:
        # Re-evaluate is_free on all events (in case scraper missed it)
        for event in events:
            if not event.is_free:
                event.is_free = _re_evaluate_free(event)

    if not include_free_only:
        logger.info("Cost filter: keeping all %d events (free_only=False)", len(events))
        return events

    kept = [e for e in events if e.is_free]
    logger.info("Cost filter: %d → %d events (free_only=True)", len(events), len(kept))
    return kept


def _re_evaluate_free(event: Event) -> bool:
    """Secondary check: look for free indicators in all event text.

    Priority order:
    1. Strong free phrases in title/description → True (event-level signal wins over
       a paid source default, e.g. a "Free Admission Day" at a paid-admission museum).
    2. Paid signals anywhere in full text → False.
    3. "free" in the cost field → True (handles sources like Art Institute /
       History Museum whose cost strings are "free (IL residents ...)").
    """
    title_desc = f"{event.title} {event.description}".lower()
    cost_lower = event.cost.lower()

    # 1. Explicit free event in the event's own title / description
    strong_free = [
        "free admission", "free entry", "free for", "free day", "free museum",
        "no admission", "no cost", "no charge", "complimentary",
    ]
    if any(p in title_desc for p in strong_free):
        return True

    # 2. Paid signals anywhere (including cost field and description)
    paid_words = [
        "$", "fee required", "admission required", "ticket required",
        "registration fee", "paid admission",
    ]
    full_text = f"{cost_lower} {title_desc}"
    if any(p in full_text for p in paid_words):
        return False

    # 3. Source-level cost field says "free" (e.g. "free (IL residents)")
    return "free" in cost_lower
