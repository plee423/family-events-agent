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
    """Secondary check: look for free indicators in all event text."""
    text = f"{event.cost} {event.title} {event.description}".lower()
    free_words = ["free", "no cost", "no charge", "complimentary", "no admission"]
    paid_words = ["$", "fee required", "admission required", "ticket required", "registration fee"]

    if any(p in text for p in paid_words):
        return False
    return any(f in text for f in free_words)
