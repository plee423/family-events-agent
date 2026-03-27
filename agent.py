"""
family-events-agent — main orchestrator and CLI entry point.

Usage:
    python agent.py run                          # Scrape all sources, generate .ics
    python agent.py run --dry-run               # Preview events without writing .ics
    python agent.py run --sources "CPL" "Zoo"  # Scrape specific sources only
    python agent.py run --location irvine       # Use alternate location config
    python agent.py sources                     # List all configured sources
    python agent.py test-source "Source Name"  # Test a single scraper
    python agent.py clear-cache                 # Delete all cached scrape data
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from hashlib import md5
from pathlib import Path
from typing import Optional

import click
import yaml

# ── Logging setup ─────────────────────────────────────────────────────────────

def setup_logging(verbose: bool = False) -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Console handler — INFO by default, DEBUG if --verbose
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))
    root.addHandler(console)

    # File handler — always DEBUG
    fh = logging.FileHandler(log_dir / "agent.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
    )
    root.addHandler(fh)


logger = logging.getLogger(__name__)

# ── Config loading ─────────────────────────────────────────────────────────────

CONFIG_DIR = Path(__file__).parent / "config"


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(location: str = "") -> dict:
    base = load_yaml(CONFIG_DIR / "settings.yaml")
    if location:
        override_path = CONFIG_DIR / f"settings_{location}.yaml"
        if override_path.exists():
            override = load_yaml(override_path)
            _deep_merge(base, override)
    return base


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base in-place (one level deep for nested dicts)."""
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            base[key].update(val)
        else:
            base[key] = val


def load_sources(location: str = "") -> list[dict]:
    if location:
        path = CONFIG_DIR / f"sources_{location}.yaml"
        if not path.exists():
            raise FileNotFoundError(
                f"No sources config found for location '{location}'. "
                f"Expected: {path}"
            )
        data = load_yaml(path)
    else:
        data = load_yaml(CONFIG_DIR / "sources.yaml")
    return data.get("sources", [])


# ── Caching ────────────────────────────────────────────────────────────────────

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _cache_path(source_name: str) -> Path:
    key = md5(source_name.encode()).hexdigest()[:12]
    return CACHE_DIR / f"{key}.json"


def cache_get(source_name: str, ttl_hours: float) -> Optional[list[dict]]:
    """Return cached events if fresh, else None."""
    path = _cache_path(source_name)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data["cached_at"])
        if datetime.now() - cached_at < timedelta(hours=ttl_hours):
            logger.debug("Cache hit for %r (age: %s)", source_name, datetime.now() - cached_at)
            return data["events"]
    except Exception as exc:
        logger.debug("Cache read failed for %r: %s", source_name, exc)
    return None


def cache_set(source_name: str, events: list) -> None:
    """Serialize events to cache."""
    path = _cache_path(source_name)
    try:
        serialized = []
        for e in events:
            d = e.__dict__.copy()
            d["date_start"] = e.date_start.isoformat()
            d["date_end"] = e.date_end.isoformat() if e.date_end else None
            serialized.append(d)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cached_at": datetime.now().isoformat(), "events": serialized}, f)
    except Exception as exc:
        logger.debug("Cache write failed for %r: %s", source_name, exc)


def cache_deserialize(raw_events: list[dict]) -> list:
    """Reconstruct Event objects from cached dicts."""
    from scrapers.base import Event
    from dateutil import parser as dateutil_parser

    events = []
    for d in raw_events:
        try:
            d["date_start"] = dateutil_parser.parse(d["date_start"])
            if d.get("date_end"):
                d["date_end"] = dateutil_parser.parse(d["date_end"])
            d.setdefault("category", "")
            events.append(Event(**d))
        except Exception as exc:
            logger.debug("Failed to deserialize cached event: %s", exc)
    return events


# ── Scraper factory ─────────────────────────────────────────────────────────────

def get_scraper(scraper_type: str, settings: dict):
    if scraper_type == "html":
        from scrapers.html_scraper import HtmlScraper
        return HtmlScraper(settings)
    elif scraper_type == "browser":
        from scrapers.browser_scraper import BrowserScraper
        return BrowserScraper(settings)
    elif scraper_type == "ical":
        from scrapers.ical_scraper import IcalScraper
        return IcalScraper(settings)
    elif scraper_type == "api":
        from scrapers.api_scraper import ApiScraper
        return ApiScraper(settings)
    elif scraper_type == "bibliocommons":
        from scrapers.bibliocommons_scraper import BibliocommunesScraper
        return BibliocommunesScraper(settings)
    elif scraper_type == "tribe_events":
        from scrapers.tribe_events_scraper import TribeEventsScraper
        return TribeEventsScraper(settings)
    elif scraper_type == "chicago_aem":
        from scrapers.chicago_aem_scraper import ChicagoAemScraper
        return ChicagoAemScraper(settings)
    elif scraper_type == "tockify":
        from scrapers.tockify_scraper import TockifyScraper
        return TockifyScraper(settings)
    elif scraper_type == "book_cellar":
        from scrapers.book_cellar_scraper import BookCellarScraper
        return BookCellarScraper(settings)
    elif scraper_type == "nature_museum":
        from scrapers.nature_museum_scraper import NatureMuseumScraper
        return NatureMuseumScraper(settings)
    elif scraper_type == "eventbrite":
        from scrapers.eventbrite_scraper import EventbriteScraper
        return EventbriteScraper(settings)
    else:
        raise ValueError(f"Unknown scraper type: {scraper_type!r}")


# ── Scrape one source ──────────────────────────────────────────────────────────

def scrape_source(source: dict, settings: dict, use_cache: bool = True) -> list:
    """Scrape a single source. Returns a list of Event objects."""
    scraping_cfg = settings.get("scraping", {})
    ttl = float(scraping_cfg.get("cache_ttl_hours", 6))
    source_name = source["name"]

    if use_cache:
        cached = cache_get(source_name, ttl)
        if cached is not None:
            events = cache_deserialize(cached)
            logger.info("[cache] %s: %d events", source_name, len(events))
            return events

    scraper_type = source.get("scraper", "html")
    try:
        scraper = get_scraper(scraper_type, settings)
        events = scraper.scrape(source)
        if use_cache and events:  # Don't cache empty results — could be missing token or transient error
            cache_set(source_name, events)
        return events
    except Exception as exc:
        logger.error("FAILED [%s]: %s", source_name, exc)
        logger.debug("Traceback:", exc_info=True)
        return []


# ── Filter pipeline ────────────────────────────────────────────────────────────

def run_filters(events: list, settings: dict, sources: list[dict] | None = None) -> list:
    """Run the full filter pipeline: age → cost → location → dedup."""
    from filters.age_filter import filter_by_age
    from filters.cost_filter import filter_by_cost
    from filters.location_filter import filter_by_location
    from filters.dedup_filter import deduplicate
    from datetime import datetime, timedelta

    # Date window filter (before other filters, saves geocoding time)
    prefs = settings.get("preferences", {})
    days_ahead = prefs.get("days_ahead", 30)
    now = datetime.now()
    cutoff = now + timedelta(days=days_ahead)
    before = len(events)
    # Strip timezone info before comparison — some scrapers return tz-aware datetimes
    # (Tockify, Chicago AEM) while others return naive datetimes.
    events = [e for e in events if now <= e.date_start.replace(tzinfo=None) <= cutoff]
    logger.info("Date window filter: %d → %d events (next %d days)", before, len(events), days_ahead)

    # Keyword exclusion
    exclude_kw = [kw.lower() for kw in prefs.get("exclude_keywords", [])]
    if exclude_kw:
        before = len(events)
        events = [
            e for e in events
            if not any(kw in (e.title + e.description).lower() for kw in exclude_kw)
        ]
        logger.info("Keyword exclusion: %d → %d events", before, len(events))

    events = filter_by_age(events, settings, sources)
    events = filter_by_cost(events, settings)
    events = filter_by_location(events, settings)
    events = deduplicate(events)

    # Sort by date — strip timezone to allow comparison of naive and aware datetimes
    events.sort(key=lambda e: e.date_start.replace(tzinfo=None))

    from filters.category_assigner import assign_categories
    events = assign_categories(events)

    return events


# ── CLI ────────────────────────────────────────────────────────────────────────

@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx, verbose):
    """Family Events Agent — find baby/toddler events and generate a .ics calendar."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@cli.command()
@click.option("--sources", "-s", multiple=True, help="Scrape only these source names")
@click.option("--location", "-l", default="", help="Use alternate location config (e.g. 'irvine')")
@click.option("--dry-run", is_flag=True, help="Print events without generating .ics")
@click.option("--no-cache", is_flag=True, help="Ignore cached results and re-scrape")
@click.pass_context
def run(ctx, sources, location, dry_run, no_cache):
    """Scrape all sources, filter events, generate .ics calendar."""
    settings = load_settings(location)
    all_sources = load_sources(location)

    # Filter to specified sources if provided
    if sources:
        source_names_lower = [s.lower() for s in sources]
        all_sources = [
            src for src in all_sources
            if any(name in src["name"].lower() for name in source_names_lower)
        ]
        if not all_sources:
            click.echo(f"No sources matched: {list(sources)}", err=True)
            sys.exit(1)

    click.echo(f"Scraping {len(all_sources)} sources...")

    # Parallel scraping
    max_workers = settings.get("scraping", {}).get("max_workers", 5)
    all_events: list = []
    source_counts: dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_source = {
            executor.submit(scrape_source, src, settings, not no_cache): src
            for src in all_sources
        }
        for future in as_completed(future_to_source):
            src = future_to_source[future]
            try:
                events = future.result()
                source_counts[src["name"]] = len(events)
                all_events.extend(events)
            except Exception as exc:
                logger.error("Unexpected error from %s: %s", src["name"], exc)
                source_counts[src["name"]] = 0

    click.echo(f"\nRaw events: {len(all_events)} from {len(all_sources)} sources")

    # Filter pipeline
    click.echo("Running filters...")
    filtered = run_filters(all_events, settings, all_sources)

    if dry_run:
        _print_events(filtered)
        click.echo(f"\n[DRY RUN] {len(filtered)} events (no .ics generated)")
        return

    if not filtered:
        click.echo("No events found after filtering. Check your settings or try --no-cache.")
        return

    # Generate .ics, HTML, and JSON
    from calendar_gen.ics_builder import build_ics
    from calendar_gen.html_builder import build_html
    from calendar_gen.json_builder import build_json
    output_path = build_ics(filtered, settings)
    html_path = build_html(filtered, settings)
    json_path = build_json(filtered, settings)

    # Summary
    free_count = sum(1 for e in filtered if e.is_free)
    click.echo(
        f"\nFound {len(filtered)} events from {sum(1 for v in source_counts.values() if v > 0)} sources "
        f"({free_count} free).\nCalendar saved to: {output_path}\nHTML saved to:     {html_path}\n"
        f"JSON saved to:     {json_path}"
    )
    click.echo("\nTo import on iPhone: AirDrop the .ics file, or email it to yourself and tap the attachment.")
    click.echo(f"To view events:    open {html_path}")


@cli.command(name="sources")
@click.option("--location", "-l", default="", help="Use alternate location config")
def list_sources(location):
    """List all configured event sources."""
    all_sources = load_sources(location)
    click.echo(f"\n{'#':<4} {'Name':<45} {'Scraper':<10} {'Tags'}")
    click.echo("-" * 100)
    for i, src in enumerate(all_sources, 1):
        tags = ", ".join(src.get("tags", [])[:4])
        click.echo(f"{i:<4} {src['name']:<45} {src.get('scraper','html'):<10} {tags}")
    click.echo(f"\nTotal: {len(all_sources)} sources")


@cli.command(name="test-source")
@click.argument("source_name")
@click.option("--no-cache", is_flag=True)
@click.option("--location", "-l", default="")
@click.pass_context
def test_source(ctx, source_name, no_cache, location):
    """Test a single source's scraper and print raw events found."""
    settings = load_settings()
    all_sources = load_sources(location)

    matches = [s for s in all_sources if source_name.lower() in s["name"].lower()]
    if not matches:
        click.echo(f"No source matching '{source_name}'. Run `python agent.py sources` to see all.", err=True)
        sys.exit(1)

    for src in matches:
        click.echo(f"\nTesting: {src['name']} ({src.get('scraper','html')})")
        click.echo(f"URL: {src['url']}")
        events = scrape_source(src, settings, use_cache=not no_cache)
        if not events:
            click.echo("  No events found. Check selectors or URL.")
        else:
            click.echo(f"  Found {len(events)} raw events:")
            for e in events[:10]:
                free_tag = " [FREE]" if e.is_free else ""
                click.echo(f"  - {e.date_start.strftime('%Y-%m-%d %H:%M')}  {e.title}{free_tag}")
            if len(events) > 10:
                click.echo(f"  ... and {len(events) - 10} more")


@cli.command(name="clear-cache")
def clear_cache():
    """Delete all cached scrape data."""
    cache_files = list(CACHE_DIR.glob("*.json"))
    if not cache_files:
        click.echo("Cache is already empty.")
        return
    for f in cache_files:
        f.unlink()
    click.echo(f"Cleared {len(cache_files)} cached files.")


def _print_events(events: list) -> None:
    """Pretty-print events to console (used for --dry-run)."""
    current_date = None
    for e in events:
        date_str = e.date_start.strftime("%Y-%m-%d")
        if date_str != current_date:
            _safe_echo(f"\n-- {date_str} " + "-" * 38)
            current_date = date_str
        free_tag = " [FREE]" if e.is_free else ""
        time_str = e.date_start.strftime("%I:%M %p")
        # Only show time if it's not midnight (which means no time was parsed)
        if e.date_start.hour == 0 and e.date_start.minute == 0:
            time_str = "All day "
        _safe_echo(f"  {time_str}  {e.title}{free_tag}")
        _safe_echo(f"           {e.org_name} @ {e.location_name}")


def _safe_echo(text: str) -> None:
    """click.echo with Unicode errors replaced for Windows cp949/cp1252 consoles."""
    try:
        click.echo(text)
    except UnicodeEncodeError:
        click.echo(text.encode("ascii", errors="replace").decode("ascii"))


if __name__ == "__main__":
    cli()
