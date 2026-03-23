"""Deduplicate events that appear across multiple sources."""
from __future__ import annotations

import logging
import re
from collections import defaultdict

from scrapers.base import Event

logger = logging.getLogger(__name__)


def deduplicate(events: list[Event]) -> list[Event]:
    """
    Remove duplicate events using a normalized (title, date, location) key.
    When duplicates exist, prefer the copy with more complete information.
    """
    buckets: dict[str, list[Event]] = defaultdict(list)

    for event in events:
        key = _dedup_key(event)
        buckets[key].append(event)

    kept: list[Event] = []
    dupes = 0
    for key, group in buckets.items():
        if len(group) == 1:
            kept.append(group[0])
        else:
            best = max(group, key=_completeness_score)
            kept.append(best)
            dupes += len(group) - 1

    if dupes:
        logger.info("Dedup filter: removed %d duplicates, %d → %d events", dupes, len(events), len(kept))
    else:
        logger.info("Dedup filter: no duplicates found (%d events)", len(kept))

    return kept


def _dedup_key(event: Event) -> str:
    """Normalized key for duplicate detection."""
    title = _normalize(event.title)
    date = event.date_start.date().isoformat()
    location = _normalize(event.location_name)
    return f"{title}|{date}|{location}"


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _completeness_score(event: Event) -> int:
    """Score an event by how much info it has — higher is better."""
    score = 0
    if event.description:
        score += len(event.description)
    if event.url:
        score += 10
    if event.location_address:
        score += 5
    if event.date_end:
        score += 3
    if event.cost:
        score += 2
    if event.age_range:
        score += 2
    return score
