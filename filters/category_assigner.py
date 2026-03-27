"""Assign a display category to each event based on its tags."""
from __future__ import annotations

import logging

from scrapers.base import Event

logger = logging.getLogger(__name__)

# Ordered rules: first match wins.
CATEGORY_RULES: list[tuple[str, frozenset[str]]] = [
    ("Storytime",      frozenset(["storytime", "reading", "bookstore", "library"])),
    ("Animals",        frozenset(["animals", "zoo"])),
    ("Science & STEM", frozenset(["science", "stem", "history"])),
    ("Arts & Music",   frozenset(["art", "arts", "music", "culture"])),
    ("Outdoors",       frozenset(["outdoor", "nature", "park", "parks", "waterfront"])),
    ("Play",           frozenset(["play", "classes", "recreation", "community", "entertainment"])),
]

FALLBACK_CATEGORY = "General"


def assign_categories(events: list[Event]) -> list[Event]:
    """Mutate each event in-place with its resolved category. Returns the same list."""
    for event in events:
        event.category = _resolve(event.tags)
    logger.info("Category assignment: %d events categorized", len(events))
    return events


def _resolve(tags: list[str]) -> str:
    tag_set = {t.lower() for t in tags}
    for category_name, rule_tags in CATEGORY_RULES:
        if tag_set & rule_tags:
            return category_name
    return FALLBACK_CATEGORY
