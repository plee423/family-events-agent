"""Assign a display category to each event based on title/description content.

Uses title-keyword matching first (most accurate), then falls back to tag-based
rules. This ensures events like "LEGO Club" at a library aren't mislabeled
"Storytime" just because the source carries the 'library' tag.
"""
from __future__ import annotations

import logging

from scrapers.base import Event

logger = logging.getLogger(__name__)

# ── Title-keyword rules (ordered: first match wins) ────────────────────────────
# Checks event.title.lower(); if no match, checks event.description.lower().

TITLE_RULES: list[tuple[str, list[str]]] = [
    ("Storytime", [
        "story time", "storytime", "lapsit", "bookworm", "mother goose",
        "storypalooza", "tummy time", "tales for twos", "tales for threes",
        "bilingual story", "pajama story", "baby and toddler story",
        "big kid story", "little learners story", "preschool story",
        "family story", "infant story",
    ]),
    ("Film & Events", [
        "film screening", "teen film", "free wednesday",
        "día de los niños", "dia de los ninos", "celebration of children",
        "anime screening", "sunday cinema",
    ]),
    ("STEM", [
        "coding", "stem club", " stem", "lego", "robotics", "robot",
        "computer literacy", "artificial intelligence", " ai ",
        "maker drop", "youmedia", "cardboard lab", "3d print",
        "march into science", "mad science", "w.e. are curious",
        "high school maker", "scratch art", "science club", "science project",
        "science program", "math club",
    ]),
    ("Arts & Crafts", [
        "and crafts", "arts and", "craft", "collage", "origami",
        "papier", "sticker making", "stamping studio", "umbrella art",
        "magnetic poetry", "stitches", "band patch", "cricut",
        "tactile art", "seed flower", "color explosion", "wild collage",
        "ready to wear cardboard", "bloom and grow", "crafternoon",
        "día crafts", "dia crafts", "messy art", "art of paper",
        "art night", "pom pom", "salt painting", "coloring club",
        "adult coloring", "drawing", "watercolor", "painting class",
        "weaving", "sewing", "knit", "crochet", "pottery", "sculpture",
        "printmaking", "mural",
    ]),
    ("Music & Dance", [
        "music", "singing", "sing ", "concert", "drum", "dance", "choir",
        "instrument", "rhythm", "jazz", "orchestra", "movement to music",
        "movement class", "song", "lullaby", "karaoke",
        "baby music", "toddler music", "music class", "music together",
        "musical", "ukulele", "guitar", "piano", "violin",
    ]),
    ("Play & Games", [
        "game day", "game night", "gaming", "dungeons & dragons", " d&d",
        "super hero", "superhero", "yoga", "putt putt", "tabletop gaming",
        "tween game", "teen game", "friday games", "open play",
        "favorite animal day", "pajama day", "obstacle",
        "tumble", "gymnastics", "physical",
    ]),
    ("Community", [
        "esl practice", "english conversation", "book club",
        "coffee and connections", "walk-in hours", "healthcare",
        "teen hideaway", "teen zone", "homeschool family",
        "start growing", "garden club", "garden program",
        "literary lounge", "mystery group", "real ones read",
        "grab and go", "cursive club", "bring your own book",
        "adult book club", "social work", "wellness",
        "mather's grow", "grow-it-together", "support group",
        "homework help", "computer help", "spice club",
    ]),
]

# ── Tag-based fallback (used only when title/description keywords don't match) ──
TAG_FALLBACK_RULES: list[tuple[str, frozenset[str]]] = [
    ("Storytime",     frozenset(["storytime", "reading"])),
    ("STEM",          frozenset(["science", "stem"])),
    ("Arts & Crafts", frozenset(["art", "arts", "music", "culture"])),
    ("Music & Dance", frozenset(["music", "dance", "movement"])),
    ("Play & Games",  frozenset(["play", "classes", "recreation", "entertainment"])),
    ("Community",     frozenset(["community"])),
]

FALLBACK_CATEGORY = "General"


def assign_categories(events: list[Event]) -> list[Event]:
    """Mutate each event in-place with its resolved category. Returns the same list."""
    for event in events:
        event.category = _resolve(event)
    logger.info("Category assignment: %d events categorized", len(events))
    return events


def _resolve(event: Event) -> str:
    title = (event.title or "").lower()
    desc = (event.description or "").lower()

    # 1. Check title keywords
    for category_name, keywords in TITLE_RULES:
        if any(kw in title for kw in keywords):
            return category_name

    # 2. Check description keywords (same rules, but lower weight — only first 200 chars)
    desc_snippet = desc[:200]
    for category_name, keywords in TITLE_RULES:
        if any(kw in desc_snippet for kw in keywords):
            return category_name

    # 3. Tag-based fallback
    tag_set = {t.lower() for t in (event.tags or [])}
    for category_name, rule_tags in TAG_FALLBACK_RULES:
        if tag_set & rule_tags:
            return category_name

    return FALLBACK_CATEGORY
