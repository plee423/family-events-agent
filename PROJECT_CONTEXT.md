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
| `config/sources_irvine.yaml` | Irvine CA — 15 sources (8 LibCal ical, tribe_events, html, browser, eventbrite) |
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

- **Last updated:** 2026-03-27 (session 10)
- **Status:** Chicago pipeline fully working (~225 events). Irvine pipeline working: 319 events / 10 sources (LibCal iCal for IPL + OCPL, tribe_events for Pretend City, HTML for Bowers + City of Irvine). Age filter tightened for adult/teen false positives. OC neighborhood bounding boxes added. Web UI supports both Chicago and OC neighborhoods dynamically.

### Working sources (as of 2026-03-25)
| Source | Raw Events | Notes |
|--------|-----------|-------|
| Chicago Public Library | 249 raw | Bibliocommons API |
| Chicago History Museum | 230 raw | Tribe Events REST API; `children_only: false` |
| Chicago Cultural Center | 182 raw | Chicago AEM JSON API; `children_only: false` |
| Chicago Children's Museum | 110 raw | Tockify REST API; links to programs page |
| Millennium Park | 83 raw | Chicago AEM JSON API |
| Chicago Park District Toddler | 16 raw | Playwright, keyword=toddler |
| Chicago Park District Baby | 20 raw | Playwright, keyword=baby |
| Art Institute | 10 raw | Playwright; `children_only: false` |
| Lincoln Park Zoo | 8 raw (expected more after fix) | Playwright; now captures `.pageblock--oms-text-media` featured events (e.g. Easter egg hunt) |
| Field Museum Events | 0 raw (selector broken; expect more after fix) | Switched to Playwright; `children_only: false` |
| Field Museum Free Wednesdays | 3 raw | HTML scraper; `children_only: true` |
| National Museum of Mexican Art | 4 raw (expect more after fix) | Switched to HTML scraper; `ul li` + `h3` selectors |
| Navy Pier | 2 raw | Playwright; `children_only: false`; tightened to `article.fav-card` |
| The Book Cellar | varies | book_cellar scraper |
| Peggy Notebaert Nature Museum | varies | nature_museum scraper |

**Final output (2026-03-25):** 225 events / 14 sources after all filters

### CI / workflow fixes (session 5)

**Git push reliability — fetch-rebase-push pattern**
- Old pattern (push-fail-pull-rebase) caused two failure modes:
  1. "Unstaged changes" during rebase — fixed by committing before pull
  2. Rebase conflicts on output files from concurrent runs — fixed by `git pull --rebase -X theirs` + concurrency group
- New pattern in `commit-outputs` job: always `git fetch` → `git rebase -X theirs origin/master` → `git push`, retry loop up to 3×
- `actions/checkout@v4` uses `fetch-depth: 0` (full history for rebase)
- `concurrency: group: scrape-events, cancel-in-progress: true` — prevents two runs racing
- Confirmed working by Opus 4.6 model review

**Debug step added** to Chicago scrape job: `ls -la output/` printed after scrape to diagnose why `events_chicago.json` wasn't updating in CI (under investigation — stale file from `548951a` being carried forward).

### Filter fixes (session 5)

**Age filter (`filters/age_filter.py`) — tightened**
- Removed `"family"` from `BABY_KEYWORDS` — was causing all Navy Pier events to pass (source tags include `"family"`)
- Added `WEAK_BABY_KEYWORDS = {"family"}` — used only for `children_only=True` sources
- Added word-boundary matching via `re.search(r"\b" + re.escape(kw) + r"\b", text)` — fixes substring false positives (`"0-2"` matching `"10-20"`, `"kids"` matching `"sidekicks"`)
- Added `children_only` source-level flag: sources marked `children_only: false` in sources.yaml must have an explicit baby/toddler keyword to pass the filter; no-age-info events from those sources are **rejected** (not kept by default)
- `filter_by_age` now accepts `sources: list[dict] | None` and looks up `children_only` by `event.source_name` — no new field on Event dataclass
- `run_filters` and `agent.py run` updated to pass `all_sources` through

**Sources marked `children_only: false` in sources.yaml:**
- Navy Pier - Events (general entertainment)
- Art Institute of Chicago - Events (adult lectures common)
- Chicago History Museum - Events (adult history programs common)
- Field Museum - Events (general museum; note: Free Wednesdays stays `true`)
- Chicago Cultural Center - Events (mixed adult/family events)

**Cost fix:** `Field Museum - Events` cost changed from `""` to `"paid admission"` — prevents `_infer_free` from incorrectly tagging events as free.

### Eventbrite — rewritten to org-based API (session 6)

- `/v3/events/search/` shut down Feb 2020 — 404 for all tokens.
- `/v3/organizations/{id}/events/` also returns 404 (account-management path, requires elevated auth).
- **Correct endpoint:** `/v3/organizers/{id}/events/?expand=venue,ticket_classes` — public, works with free dev token.
- **API constraint:** Only `expand` param is accepted. `status`, `page_size`, `start_date.range_start` all return 400. Default page is 50 events. Past events filtered in Python.
- **Result:** 116 raw events across 10 orgs confirmed working locally.

**10 verified Chicago family/baby Eventbrite organizers (configured in sources.yaml):**

| # | Name | Org ID | Description |
|---|------|--------|-------------|
| 1 | Weissbluth Pediatrics | 14498519145 | Free infant CPR, sleep, breastfeeding classes |
| 2 | FAME Center | 31435451531 | FreePlay baby/caregiver art & sensory play |
| 3 | Heloise Stauff (Snuggly Start) | 120884312028 | Infant massage workshops (Oak Park) |
| 4 | Collaboration for Early Childhood | 27055420443 | Baby expos, parent workshops (Oak Park) |
| 5 | Babies & Bumps | 4423387473 | Baby expos for new/expecting parents |
| 6 | Songs 'n Swings | 25223856619 | Free baby/toddler music & movement classes |
| 7 | Music Moves Chicago | 108784994551 | Old Town School FireFlies toddler music |
| 8 | St. James Lutheran (Mini Mavericks) | 79847647193 | Free weekly drop-in play (birth–4, Lincoln Park) |
| 9 | Arts + Public Life | 12301919835 | U of C South Side FireFlies toddler music |
| 10 | Prairie District Neighborhood Alliance | 60909139173 | South Loop seasonal family events |

### New scrapers / fixes (session 4 — carried forward)
- `scrapers/tockify_scraper.py`: `website` fallback URL for CCM per-event links
- `config/sources.yaml`: CCM `website` field, Harold Washington + Near North branch-filtered CPL sources
- `.github/workflows/scrape.yml`: `EVENTBRITE_TOKEN` secret wired to both scrape jobs

### Fix 4 — cost filter restructured (session 7)

`filters/cost_filter.py` `_re_evaluate_free` now uses a 3-step priority order:
1. Strong free phrases in title/description (`"free admission"`, `"free day"`, etc.) → `True` — event-level free signal wins even when source cost is `"paid admission"`.
2. Paid signals anywhere in full text (incl. new `"paid admission"` entry) → `False`.
3. `"free"` in cost field alone → `True` — preserves correct tagging for Art Institute (`"free (IL residents under 14)"`) and History Museum (`"free (IL residents)"`). No changes to sources.yaml cost fields.

### Fix 5 — neighborhood classifier (session 7)

- `scrapers/neighborhood_classifier.py` — 30 named bounding boxes (downtown, North Side, Northwest Side, West Side, South Side, near suburbs). `classify(lat, lng) -> str` returns neighborhood or `""`.
- `scrapers/base.py` — `neighborhood: str = ""` added to `Event` dataclass.
- `filters/location_filter.py` — calls `_classify_neighborhood(lat, lng)` after distance is computed; sets `event.neighborhood`.
- `calendar_gen/json_builder.py` — `neighborhood` included in serialized JSON.
- `calendar_gen/html_builder.py` — neighborhood shown as purple `.badge-neighborhood` pill in event card meta row.

### Web UI + filter fixes (session 8)

- **Neighborhood filter** added to `public/index.html` — dynamically populated from `event.neighborhood` values after load; hidden when no neighborhoods present; filters `applyFilters` by exact match.
- **Add to Calendar button fixed** — `triggerDownload` now appends anchor to DOM before `.click()` (required by Firefox/Safari) and revokes the blob URL after 2000ms delay (was revoking synchronously before download could start).
- **CCM free tagging fixed** — `_infer_free` in `scrapers/base.py` now includes `"paid admission"`, `"members only"`, `"membership required"` in `paid_overrides`. CCM cost changed to `"paid admission (free first Sunday for Chicago residents)"` — `_infer_free` hits paid_override and returns False for all CCM events by default.
- **CCM link fixed** — `website` changed from 404 URL to `https://www.chicagochildrensmuseum.org/program-calendar`.
- **Empty-result caching fix** — `agent.py` no longer caches 0-event results (`if use_cache and events`). Prevents stale local cache from a run without EVENTBRITE_TOKEN poisoning subsequent cached runs.

### Eventbrite — 0 events (under investigation)

Root cause unknown. Age filter analysis: `age_hint="0-60 months"` → Rule 3 keeps all events; not the issue. Added CI debug step: `python agent.py test-source "Eventbrite - Chicago Family Events" --no-cache` runs before the main scrape and prints raw event counts per org. Check next CI run's "Debug Eventbrite raw events" step output to diagnose:
- If API errors per org → token invalid or org IDs stale
- If events fetched but 0 in final output → location filter dropping them (check venue addresses)
- If 0 fetched per org → orgs have no upcoming events right now

### Fixes (session 9)

**Neighborhood filter confirmed working**
- `public/index.html`: neighborhood filter bar populates dynamically from `event.neighborhood` values after data loads; hidden when no neighborhoods present; buttons filter by exact match
- `calendar_gen/html_builder.py`: purple `.badge-neighborhood` pill shown in event card meta row
- `scrapers/neighborhood_classifier.py`: 30 bounding boxes covering Loop, West Loop, South Loop, River North, Lincoln Park, Hyde Park, Oak Park, Evanston, etc.

**CCM free-tag fix (`filters/cost_filter.py` `_re_evaluate_free`)**
- Added step 0: if `event.cost` contains `"paid admission"`, short-circuit using only event *title* (not description) for strong-free phrases. Prevents CCM event descriptions like "free for all families" from overriding the source-level paid admission cost.
- CCM's `cost: "paid admission (free first Sunday for Chicago residents)"` now correctly blocks all CCM events from being tagged `[FREE]` unless the event TITLE contains a genuine free-admission phrase (e.g., "Free First Sunday").

**Eventbrite pagination fixed (`scrapers/eventbrite_scraper.py`)**
- Root cause: API returns events in ascending date order (oldest first). Orgs with many past events filled all 50 slots on page 1 with past events; `start_after` dropped all of them → 0 results.
- Fix: `_fetch_org_events` now paginates using `pagination.continuation` token, up to `max_pages` (default 5, configured in sources.yaml).  Stops as soon as `has_more_items=False` or continuation is absent.
- Per-org summary logged at INFO: total fetched, past dropped, upcoming kept — visible in CI debug step.

**Vercel cache headers (`vercel.json`)**
- Added `Cache-Control: no-cache, must-revalidate` for all `*.json` and `events_*.html` routes
- Prevents browser/CDN from serving stale event data after nightly scrape pushes

### Known issues / next steps
- **Eventbrite:** If CI debug step shows `API returned 0 total events` per org → orgs are seasonally inactive (expected). If shows `N total, N dropped as past` → pagination needed (all 50 events are past). Check next CI run's "Debug Eventbrite raw events" logs.
- **Songs 'n Swings:** Monitor — 144 past events but 0 upcoming; may become active again
- Tockify events show `05:00 AM` in console dry-run (UTC not converted). HTML/JSON output correct via pytz.

### Fixes (session 11) — Scraper selector audit

**Root cause identified:** Several browser/HTML scrapers had wrong CSS selectors, causing events to be missed or incorrectly parsed. Discovered via live HTML inspection (WebFetch) while investigating why LPZ Easter egg hunt wasn't appearing.

**Lincoln Park Zoo (`config/sources.yaml`)**
- `event_card` widened to `.card__content, .pageblock--oms-text-media` — featured seasonal events (e.g. Spring Egg-Stravaganza / Easter egg hunt) use a different HTML layout than regular cards
- `title` fixed from `p.h4 a` (non-existent selector) to `h2, h4 a` — regular cards use `<h4><a>`, featured sections use `<h2>`
- `link` fixed from `p.h4 a` to `h4 a, a`
- Added `wait_selector: ".card__content"` — cards are lazy-loaded; 2s flat buffer was insufficient

**Field Museum - Events (`config/sources.yaml`)**
- Switched from `html` → `browser` scraper — page is React-rendered; static requests returns empty containers
- `event_card` fixed from `li.event-card` (doesn't exist) to `div.event-item, div.event-card`
- `title` fixed from `a.h4` to `h3.event-title`
- `date` fixed from `h6.h6` to `h6.event-date`; added `time: "span.event-time"`
- `link` fixed from `a.h4` to `a`

**Navy Pier (`config/sources.yaml`)**
- `event_card` tightened from broad `article, [class*='card']...` to `article.fav-card`
- `title` tightened from `h2, h3, [class*='title']...` to `h3.fav-card__title`
- `link` updated to `a.fav-card__link, a`

**National Museum of Mexican Art (`config/sources.yaml`)**
- Switched from `browser` → `html` scraper — content is static HTML, browser scraper not needed
- `event_card` changed from `.Events--listing li, ul li, li` (overly broad, matches nav) to `ul li` — `h3` presence inside li naturally filters to event items only
- `title` fixed from `a` (returned full anchor text including date) to `h3`
- `date` simplified from `p, span, div` to `p`
- `location` set to `""` — location is embedded in the same `<p>` as date, can't separate

**`_clean_date_str` in `scrapers/base.py`**
- Added em-dash/en-dash date range handling: `"Nov 21, 2025 – Apr 26, 2026"` → `"Nov 21, 2025"`
- Fixes NMMA date parsing where exhibitions span date ranges

### Fixes (session 10)

**Age filter tightened — adult/teen false positives removed (`filters/age_filter.py`)**
- Added `"adult"`, `"teen"`, `"teens"` to `ADULT_KEYWORDS`.
- Root cause: OCPL/IPL iCal feeds include ALL branch programs (adult literacy, teen clubs, etc.) not just children's events. Previous ADULT_KEYWORDS only rejected very specific phrases ("adults only", "teen only") — bare "adult" and "teen" passed through.
- Rule 1 (adult-reject) runs before Rule 2 (baby-keep), so "Adult Enrichment Storytime" is rejected despite containing "storytime".
- Word-boundary matching (`\bteen\b`) ensures "TeensTeach" (Pretend City children's museum) is NOT rejected — it's one camelCase word with no boundary after "teen".

**OC neighborhood bounding boxes added (`scrapers/neighborhood_classifier.py`)**
- Added 11 Orange County bounding boxes after the Chicago section: Rancho Santa Margarita, Aliso Viejo, Laguna Hills, Lake Forest, Tustin, Santa Ana, Costa Mesa, Huntington Beach, Fullerton, Irvine, Orange County (broad fallback).
- Chicago and OC lat ranges don't overlap (~41-42°N vs ~33-34°N) — no conflicts.
- Ordered specific→broad so named cities win over the "Irvine" broad box.
- "Orange County" is the OC equivalent of "Chicago" — a catch-all for unmatched OC coords.

**Web UI updated for OC neighborhoods (`public/index.html`)**
- `NEIGHBORHOOD_CATCHALLS = new Set(['Chicago', 'Orange County'])` defined as a module-level constant (was previously only `'Chicago'` hardcoded inline).
- Neighborhood filter buttons now exclude both "Chicago" and "Orange County" catch-alls.
- Neighborhood badge in event cards also excludes both catch-alls.
- "Irvine" IS shown as a button/badge (unlike "Chicago") — it's a specific city, not a catch-all, and useful for filtering against Tustin/Santa Ana/Laguna Hills events.

---

## Irvine Sources (`config/sources_irvine.yaml`)

> **Last expanded:** 2026-03-27 (session 10)

### Working sources (as of 2026-03-27)

| Source | Scraper | Raw Events | Notes |
|--------|---------|-----------|-------|
| Irvine PL - Heritage Park | ical (LibCal cid=22833) | 141 | Baby Storytime, Stay & Play |
| Irvine PL - Katie Wheeler | ical (LibCal cid=22737) | 62 | Toddler Storytime, Baby Storytime |
| Irvine PL - University Park | ical (LibCal cid=22834) | 112 | |
| OCPL - Tustin Branch | ical (LibCal cid=19158) | 140 | Baby/Toddler Storytime + Stay & Play |
| OCPL - El Toro Branch | ical (LibCal cid=19135) | 178 | Play and Learn (0-4), Family Storytime |
| OCPL - Aliso Viejo Branch | ical (LibCal cid=19125) | 125 | |
| OCPL - Laguna Hills Branch | ical (LibCal cid=19148) | 173 | |
| OCPL - Rancho Santa Margarita | ical (LibCal cid=19153) | 201 | |
| Pretend City Children's Museum | tribe_events | 145 | Same Tribe Events REST API as Chicago History Museum |
| City of Irvine | html | 40 | Drupal table layout; confirmed working |
| Bowers Museum | html | 0 | Selectors correct (`.sppb-addon-event-list-item`); no 2026 programs posted yet |

**Final output (2026-03-27):** 319 events / 10 sources after all filters (296 free)

### Failing / pending sources

| Source | Issue | Fix needed |
|--------|-------|-----------|
| Discovery Cube OC | Playwright not installed | `pip install playwright && playwright install chromium` |
| Santa Ana Zoo | Playwright not installed | Same |
| Eventbrite - Irvine | EVENTBRITE_TOKEN not set | Set env var; 3 OC org IDs configured |

### Key notes
- Irvine PL and OCPL use **LibCal** (SpringShare) for events — NOT Bibliocommons gateway. One cid per URL (multi-cid not supported).
- LibCal iCal URL: `https://library.libcal.com/ical_subscribe.php?src=p&cid=BRANCH_ID`
- Discovery Cube: Tribe Events REST API returns 404 (disabled); browser scraper needed with `wait_selector: ".tribe-events-calendar-list__event"` but DOM selector may need updating if events don't appear.
- Santa Ana Zoo: Events Manager iCal endpoints 404 (feed disabled); switched to browser scraper.
- Nominatim geocoding was rate-limited (429) during the 2026-03-27 run — location filter kept all 332 events (no coordinate data available for filtering). Re-run later for distance-based filtering.
- Deferred (no dated events available): OCLS (Communico JS widget), OCMA (recurring schedule only), Irvine Spectrum Center (single description page).

---

## Future Ideas

- **Daily cron + auto-email:** Schedule `agent.py run` via Windows Task Scheduler, email `.ics` to wife automatically
- **Weekly digest email:** HTML summary of the week's events instead of raw `.ics`
- **iCloud CalDAV push:** Push events directly to a shared calendar via iCloud CalDAV API
- **More APIs:** Eventbrite API, Meetup API, Google Calendar embed scraper
- **SMS alerts:** Tomorrow's free events via Twilio

---

## Notes

- Personal use only — not commercial
- Polite scraping: 1s delay between requests, 6h cache TTL, custom User-Agent
- No external AI APIs — zero ongoing cost
- Development environment: Windows 11
