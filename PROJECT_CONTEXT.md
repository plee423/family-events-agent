# Family Events Agent — Project Context

> **This file is the authoritative living document for project state.**
> Update it after every major change. Claude reads it to regain context after a compacted session.

**What it does:** Scrapes 20+ Chicago-area websites for baby/toddler-friendly events, filters them, and generates a `.ics` calendar file that imports directly into iPhone/Apple Calendar.

**Why:** Eliminates the manual chore of checking 15+ organization websites each week to find events appropriate for a baby/toddler (born 2025-03-01, Chicago).

---

## Architecture

```
config/sources.yaml → Scrapers (parallel) → Raw Events
                                                  ↓
                                           Age Filter
                                                  ↓
                                           Cost Filter
                                                  ↓
                                           Location Filter (geocoding via geopy/Nominatim)
                                                  ↓
                                           Dedup Filter
                                                  ↓
                                           .ics Builder → output/family_events_YYYY-MM-DD_YYYY-MM-DD.ics
```

---

## Entry Point

`agent.py` — Click CLI with commands:
- `run` — scrapes all sources, filters, generates .ics
- `run --dry-run` — prints events, no file written
- `run --sources "Name"` — scrape specific sources only
- `run --location irvine` — use alternate city config
- `sources` — list all configured sources
- `test-source "Name"` — debug a single scraper
- `clear-cache` — wipe cached scrape data

Parallel scraping via `ThreadPoolExecutor(max_workers=5)`.

---

## Key Files

| File | Purpose |
|------|---------|
| `agent.py` | CLI + orchestrator (scrape → filter → .ics) |
| `config/settings.yaml` | Child dob, home lat/lng, filter prefs |
| `config/sources.yaml` | Chicago sources |
| `config/sources_irvine.yaml` | Irvine CA stubs for future city move |
| `scrapers/base.py` | `Event` dataclass + `BaseScraper` ABC + `parse_with_selectors()` |
| `scrapers/html_scraper.py` | requests + BeautifulSoup, CSS selectors |
| `scrapers/ical_scraper.py` | Parses .ics feeds directly |
| `scrapers/api_scraper.py` | JSON API endpoints with `field_map` config |
| `scrapers/browser_scraper.py` | Playwright headless Chromium (JS pages) |
| `scrapers/bibliocommons_scraper.py` | Bibliocommons library sites |
| `filters/age_filter.py` | Keyword + age-range matching, rejects adult-only events |
| `filters/cost_filter.py` | Flags free events, optionally filters paid ones |
| `filters/location_filter.py` | Geocodes addresses, haversine distance, rejects beyond radius |
| `filters/dedup_filter.py` | Normalizes (title, date, location) key; keeps most complete copy |
| `calendar_gen/ics_builder.py` | Builds RFC-5545 .ics with VTIMEZONE, stable UIDs, 2 VALARMs |
| `calendar_gen/html_builder.py` | Mobile-first HTML events page (filename from settings) |
| `calendar_gen/json_builder.py` | Serializes events to JSON for web UI |
| `public/index.html` | Web app: city switcher, filters, per-event + bulk .ics download |
| `vercel.json` | Vercel static hosting config (serves `public/` directory) |
| `.github/workflows/scrape.yml` | Nightly cron: Chicago + Irvine scrape in parallel, commits outputs |
| `CLAUDE.md` | AI assistant instructions and scraping best practices |
| `PROJECT_CONTEXT.md` | This file — living project state document |

---

## Event Dataclass (`scrapers/base.py`)

```python
@dataclass
class Event:
    title: str
    date_start: datetime
    org_name: str
    date_end: Optional[datetime]
    location_name: str
    location_address: str
    location_lat: Optional[float]
    location_lng: Optional[float]
    description: str
    url: str
    cost: str          # "free", "$10", "free (IL residents)", etc.
    is_free: bool
    age_range: str     # "0-24 months", "all ages", etc.
    tags: list[str]
    distance_miles: Optional[float]
    source_name: str
    # Properties:
    uid            # sha256(title|date_start|location_name|org_name)[:32] — stable across runs
    display_title  # "[FREE] Title" or "Title"
```

---

## Config: `settings.yaml`

```yaml
child:
  birth_date: "2025-03-01"
  age_range_months: [0, 36]
location:
  city: Chicago, state: IL, zip: 60601
  home_lat: 41.8827, home_lng: -87.6233
  max_radius_miles: 10
  timezone: America/Chicago
preferences:
  include_free_only: false
  highlight_free: true
  days_ahead: 30
  exclude_keywords: [adults-only, 21+, wine, beer, cocktail]
  include_keywords: [baby, toddler, storytime, family, kids, infant, preschool, ...]
output:
  filename_template: family_events_{start}_{end}.ics
  calendar_name: Family Events
  calendar_color: "#FF6B9D"
scraping:
  cache_ttl_hours: 6
  request_delay_seconds: 1.0
  max_workers: 5
  user_agent: FamilyEventsAgent/1.0 (personal family calendar tool)
  browser_timeout_seconds: 30
```

---

## Chicago Sources (`config/sources.yaml`)

**Libraries**
- Chicago Public Library — Events
- Chicago Public Library — Harold Washington
- Chicago Public Library — Near North

**Museums**
- Field Museum, Shedd Aquarium, Museum of Science and Industry, Art Institute of Chicago
- Chicago Children's Museum, Chicago History Museum, National Museum of Mexican Art, Peggy Notebaert Nature Museum

**Parks & Recreation**
- Chicago Park District — Toddler Programs
- Chicago Park District — Baby Programs
- Maggie Daley Park, Millennium Park

**Other**
- Lincoln Park Zoo, Chicago Cultural Center, Navy Pier, The Book Cellar, Volumes Bookcafe

---

## Caching

- `cache/` directory, JSON files keyed by `md5(source_name)[:12]`
- TTL: 6 hours (configurable in `settings.yaml`)
- Serializes Event dicts with ISO timestamps; deserialized back to `Event` objects on read

---

## .ics Output Features

- `VTIMEZONE` component — required for Apple Calendar timezone handling
- Stable UIDs via `sha256(title+date+location+org)[:32]` — safe to re-import without duplicates
- `DTEND` defaults to `DTSTART + 1 hour` if not provided
- Two `VALARM`s per event: 24h before and 2h before
- `SEQUENCE: 0`
- `DESCRIPTION` includes: organizer, cost, age range, distance from home, full description, URL

---

## Dependencies (`requirements.txt`)

`requests`, `beautifulsoup4`, `icalendar`, `pyyaml`, `geopy`, `python-dateutil`, `playwright`, `lxml`, `tenacity`, `click`, `pytz`

Dev: `pytest`, `pytest-cov`

Virtual env at `.venv/` (Windows: activate with `.venv\Scripts\activate`)

---

## Current State

> **Update this section after every significant session.**

- **Last updated:** 2026-03-23 (session 3)
- **Git:** Single commit — "Initial commit: family events agent project"
- **Status:** Pipeline fully working. Web app + GitHub Actions workflow added. Ready for Vercel deploy and first full --no-cache run.

### Working sources (as of 2026-03-23)
| Source | Events | Notes |
|--------|--------|-------|
| Chicago Public Library | 249 raw | Bibliocommons API |
| Chicago History Museum | 230 raw (5 pages) | Tribe Events REST API |
| Chicago Cultural Center | 182 raw | Chicago AEM JSON API |
| Chicago Children's Museum | 115 raw (3 pages) | Tockify REST API |
| Millennium Park | 83 raw | Chicago AEM JSON API |
| Chicago Park District Toddler | 16 raw | Playwright, keyword=toddler |
| Chicago Park District Baby | 20 raw | Playwright, keyword=baby |
| Art Institute | 9 raw | Playwright |
| Lincoln Park Zoo | 8 raw | Playwright |
| Field Museum Events | 8 raw | HTML scraper |
| Field Museum Free Wednesdays | 3 raw | HTML scraper |
| National Museum of Mexican Art | 4 raw | Playwright, partial fix |
| Navy Pier | 2 raw | Playwright |

### Sources returning 0 (known issues)
| Source | Reason | Path to fix |
|--------|--------|-------------|
| Peggy Notebaert Nature Museum | Events in HTML but class names opaque/minified | Inspect via browser DevTools |
| Shedd Aquarium | WAF returns 403 to all non-browser UAs | Investigate Tessitura/ticketing API via DevTools Network tab |
| The Book Cellar | Drupal `<td>` selectors not matching rendered output | Further investigation needed |

### Removed sources
- **Griffin MSI** — domain changed `msichicago.org` → `griffinmsi.org`, fully React/JS-rendered, no calendar page
- **Maggie Daley Park** — no event calendar exists; site is informational only

### Scraper files
- `scrapers/tribe_events_scraper.py` — Tribe Events WP REST API with pagination
- `scrapers/chicago_aem_scraper.py` — Chicago.gov AEM double-JSON endpoint with tag filter
- `scrapers/tockify_scraper.py` — Tockify REST API with Unix timestamp pagination

### Output files
- `calendar_gen/ics_builder.py` — RFC-5545 .ics file with VTIMEZONE, stable UIDs, 2 VALARMs
- `calendar_gen/html_builder.py` — mobile-first HTML page (`output/events.html`): card layout grouped by date, free/paid badges, SVG icons, clickable event links, timezone-corrected display times

### Bug fixes applied
- `agent.py` `run_filters`: date window filter + sort use `.replace(tzinfo=None)` for naive/aware datetime mix
- `chicago_aem_scraper.py`: handles both `{ "calendarData": "..." }` wrapper and raw JSON array
- `filters/location_filter.py`: persistent geocoding cache at `cache/geocode_cache.json`; `max_retries=0`, `swallow_exceptions=False` so `GeocoderRateLimited` propagates to our handler; session-level `_geocoding_rate_limited` flag — first 429 disables all further Nominatim calls instantly, pipeline completes in seconds instead of minutes
- `calendar_gen/html_builder.py`: Windows-compatible date/time formatting — `%-d` and `%-I` are Linux-only; replaced with try/except falling back to `%d`/`%I` + `lstrip("0")`

### Bug fixes (session 3 — post-Actions run)
- `bibliocommons_scraper.py`: `_fetch_branches()` now extracts `address` from API alongside name → `location_address` set on all CPL/IPL/OCPL events → location filter can now geocode and distance-filter library events correctly
- `bibliocommons_scraper.py`: hardcoded `chipublib.bibliocommons.com` event URL replaced with `f"https://{library_id}.bibliocommons.com/events/{id}"` — Irvine and OCPL now get correct URLs
- `sources_irvine.yaml`: added missing `library_id: "irvine"` to Irvine Public Library — was defaulting to `"chipublib"` causing all 156 Irvine events to come from Chicago CPL
- `sources_irvine.yaml`: replaced stub sources with verified scrapers (see below)

### Irvine sources (verified 2026-03-24)
| Source | Scraper | Notes |
|--------|---------|-------|
| Irvine Public Library | bibliocommons (`library_id: "irvine"`) | Fixed — was scraping CPL |
| Orange County Public Library | bibliocommons (`library_id: "ocpl"`) | New — confirmed same Bibliocommons platform |
| Pretend City Children's Museum | tribe_events | Confirmed 149 events via REST API |
| Bowers Museum | html (`h3.sppb-addon-title`) | Confirmed server-rendered Joomla; selectors need test-source verification |
| City of Irvine | html (`table tr td`) | Confirmed server-rendered Drupal table |
| Discovery Cube OC | browser | JS/AJAX-rendered; AJAX endpoint unknown — low confidence, needs DevTools investigation |

### Web app / deployment (added session 3)
- `public/index.html` — self-contained SPA: city switcher (Chicago/Irvine), age/cost/when/venue filters, per-event .ics download (JS-generated), bulk .ics download of filtered events, HTML page download link
- `vercel.json` — serves `public/` as static site root
- `.github/workflows/scrape.yml` — runs Chicago + Irvine scrapers as parallel jobs; commit job waits for both, copies JSON/ICS/HTML to `public/`, pushes to main
- `calendar_gen/json_builder.py` — new output: `output/events_{city}.json` consumed by web app
- `config/settings_irvine.yaml` — Irvine location overrides (merged on top of `settings.yaml`)
- `config/sources_irvine.yaml` — Irvine sources: IPL uses `bibliocommons` scraper (confirmed same platform), Pretend City uses `tribe_events` scraper, others are html/browser stubs needing verification
- `agent.py` — now loads `settings_{location}.yaml` override when `--location` is passed; outputs JSON alongside .ics and .html
- `calendar_gen/html_builder.py` — now uses `settings['output']['html_filename']` instead of hardcoded `events.html`
- `config/settings.yaml` — added `json_filename: events_chicago.json`, `html_filename: events_chicago.html`

### Known issues / next steps
- **Deploy to Vercel:** Push repo to GitHub, connect to Vercel (import project → auto-detects `public/` → deploy)
- **Trigger first Actions run:** Go to GitHub → Actions → Scrape Events → Run workflow (manual trigger)
- **Verify Irvine scrapers:** `python agent.py test-source "Irvine Public Library" --location irvine --no-cache` etc.
- Nominatim geocode cache still empty — run `python agent.py run --no-cache` when rate limit resets
- Tockify events show `05:00 AM` in console dry-run (UTC not converted). HTML/JSON output correct via pytz.
- The Book Cellar still returns 0 — Drupal `<td>` structure needs DevTools verification
- Tests not yet reviewed or run

---

## Future Ideas

- **Daily cron + auto-email:** Schedule `agent.py run` via Windows Task Scheduler, email `.ics` to wife automatically
- **Weekly digest email:** HTML summary of the week's events instead of raw `.ics`
- **iCloud CalDAV push:** Push events directly to a shared calendar via iCloud CalDAV API
- **More APIs:** Eventbrite API, Meetup API, Google Calendar embed scraper
- **SMS alerts:** Tomorrow's free events via Twilio
- **Irvine CA:** Sources stubbed in `config/sources_irvine.yaml` — family may relocate

---

## Notes

- Personal use only — not commercial
- Polite scraping: 1s delay between requests, 6h cache TTL, custom User-Agent
- No external AI APIs — zero ongoing cost
- Development environment: Windows 11
