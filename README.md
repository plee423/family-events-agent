# Family Events Agent

Automatically scrapes 20+ Chicago-area organizations for baby/toddler events, filters them by age, cost, and distance, and outputs a `.ics` calendar file that imports directly into iPhone/Apple Calendar. Also runs nightly on GitHub Actions and publishes a live web UI.

**The problem it solves:** Instead of checking 15+ organization websites every week, run one command and get a ready-to-import calendar with events filtered for your child's age and your neighborhood.

---

## Live Output

- **Web UI:** Deployed to Vercel — city switcher (Chicago / Irvine), neighborhood filter, free-events filter, per-event and bulk `.ics` download
- **Nightly scrape:** GitHub Actions cron runs every night, commits updated `.json`, `.html`, and `.ics` files to `output/`
- **Current output:** ~225 Chicago events and ~319 Irvine/OC events after all filters

---

## Quick Start

### 1. Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

pip install -r requirements.txt
playwright install chromium     # Required for JS-rendered pages
```

### 2. Configure for your family

Edit `config/settings.yaml`:
- Set your child's `birth_date`
- Set your `home_lat` / `home_lng` and `zip`
- Adjust `max_radius_miles` (default: 10 miles)
- Set `days_ahead` (default: 30)

### 3. Run

```bash
python agent.py run
```

The `.ics` file is saved to `output/family_events_YYYY-MM-DD_YYYY-MM-DD.ics`.

### 4. Import to iPhone

- **AirDrop** the file from your computer → tap "Add to Calendar"
- **Email** it to yourself → tap the attachment in Mail
- **iCloud Drive** → Files app → tap the file → "Add to Calendar"

---

## CLI Reference

```bash
# Scrape all sources, generate .ics + JSON + HTML
python agent.py run

# Preview events without writing any files
python agent.py run --dry-run

# Scrape specific sources only
python agent.py run --sources "Chicago Public Library" "Lincoln Park Zoo"

# Force re-scrape, bypass 6-hour cache
python agent.py run --no-cache

# Use alternate city config (Irvine, CA)
python agent.py run --location irvine

# List all configured sources
python agent.py sources

# Test and debug a single scraper
python agent.py test-source "Chicago Public Library"
python agent.py test-source "Lincoln Park Zoo" --no-cache

# Clear cached scrape data
python agent.py clear-cache

# Verbose/debug logging
python agent.py -v run
```

---

## How It Works

```
config/sources.yaml
       │
       ▼  (parallel, up to 5 threads)
20+ Scrapers  ──────────────────────────────────────────────┐
       │                                                     │
       ▼                                                     │
Raw Events (~500–800)                               cache/ (6h TTL)
       │
       ▼
Age Filter        keeps events with baby/toddler keywords; rejects adult/teen
       │
       ▼
Cost Filter       flags free events with [FREE] prefix
       │
       ▼
Location Filter   geocodes addresses → haversine distance → drops events >10 mi
                  also classifies events into named neighborhoods
       │
       ▼
Dedup Filter      normalizes (title, date, location) key; keeps most complete copy
       │
       ▼
.ics Builder  →  output/family_events_YYYY-MM-DD_YYYY-MM-DD.ics
JSON Builder  →  output/events_chicago.json
HTML Builder  →  output/events_chicago.html
```

### Scraper types (11 total)

| Type | When used |
|------|-----------|
| `ical` | `.ics` feed URLs (LibCal library branches) |
| `bibliocommons` | Chicago Public Library via Bibliocommons API |
| `tribe_events` | WordPress sites using Tribe Events REST API |
| `tockify` | Sites embedding Tockify calendar widget |
| `chicago_aem` | Chicago.gov AEM JSON endpoints |
| `eventbrite` | Eventbrite organizer pages (public API) |
| `api` | Generic JSON API endpoints |
| `html` | Static server-rendered HTML (requests + BeautifulSoup) |
| `browser` | JS-rendered pages (Playwright headless Chromium) |
| `fieldmuseum` | Custom: reads `__NEXT_DATA__` JSON from Field Museum |
| `navypier` | Custom: Playwright + `data-date` attribute on `div.event-tile` |

### .ics compatibility (Apple Calendar)

- `VTIMEZONE` component included — required for Apple Calendar timezone handling
- Stable UIDs via `sha256(title + date + location + org)[:32]` — re-importing never creates duplicates
- Two `VALARM` reminders per event: 24 hours before and 2 hours before
- `DTEND` defaults to `DTSTART + 1 hour` when end time is unknown
- `SEQUENCE: 0`

---

## Sources

### Chicago (`config/sources.yaml`) — ~225 events after filters

**Libraries**
- Chicago Public Library (Bibliocommons API — babies & toddlers audience filter)
- CPL Harold Washington branch
- CPL Near North branch

**Museums**
- Field Museum (custom `__NEXT_DATA__` scraper — 64 raw events)
- Field Museum Free Wednesdays
- Chicago Children's Museum (Tockify API)
- Chicago History Museum (Tribe Events REST API)
- Art Institute of Chicago (Playwright)
- National Museum of Mexican Art (HTML)
- Peggy Notebaert Nature Museum

**Parks & Recreation**
- Chicago Park District — Toddler Programs (Playwright)
- Chicago Park District — Baby Programs (Playwright)
- Millennium Park (Chicago AEM JSON)
- Maggie Daley Park

**Other**
- Lincoln Park Zoo (Playwright — `.card__content` + featured `.pageblock` sections)
- Navy Pier (custom Playwright scraper — `div.event-tile`, `data-date` attribute)
- Chicago Cultural Center (Chicago AEM JSON)
- The Book Cellar, Volumes Bookcafe
- Eventbrite — 10 verified Chicago family/baby organizers

### Irvine / Orange County (`config/sources_irvine.yaml`) — ~319 events after filters

**Libraries (LibCal iCal feeds)**
- Irvine Public Library — Heritage Park, Katie Wheeler, University Park branches
- OCPL — Tustin, El Toro, Aliso Viejo, Laguna Hills, Rancho Santa Margarita branches

**Other**
- Pretend City Children's Museum (Tribe Events REST API)
- City of Irvine Parks & Recreation (HTML)
- Bowers Museum (HTML — no 2026 programs posted yet)

---

## Neighborhood Classification

Events are geocoded and assigned a neighborhood label (e.g., "Lincoln Park", "West Loop", "Hyde Park" for Chicago; "Irvine", "Tustin", "Costa Mesa" for OC). The web UI displays neighborhood badges and a filter bar. Chicago and OC bounding boxes don't overlap — both cities work from the same classifier.

---

## Multi-City Support

The system has no hardcoded city references. To add a city:

1. Create `config/sources_{city_slug}.yaml`
2. Create `config/settings_{city_slug}.yaml` (overrides home coordinates, radius, timezone)
3. Run: `python agent.py run --location {city_slug}`

### Agent-assisted city expansion

Three agent workflows in `agents/` automate the tedious parts:

| Step | Trigger | What it does |
|------|---------|--------------|
| 1. Discovery | `"find sources for [City]"` | WebSearch for orgs → writes draft `sources_{slug}.yaml` with `scraper: TBD` |
| 2. Selection | `"select scrapers for [slug]"` | Fetches each URL → determines scraper type + fills in selectors/field_map |
| 3. Coding | `"write scraper for '[Name]'"` | Writes `scrapers/{name}_scraper.py` for sites that need a custom scraper |

Most sites match one of the 11 existing scraper types — the Selection Agent assigns them automatically. Custom Python code is only needed for the few sites with proprietary formats.

---

## CI / Automation

`.github/workflows/scrape.yml` runs nightly:
- Chicago and Irvine scrapes run **in parallel** as separate jobs
- Each job: scrapes → filters → writes output files → commits to `master`
- Concurrency group prevents two runs from racing on the same branch
- Push uses `git fetch → rebase -X theirs → push` (retry up to 3×) to handle race conditions between parallel jobs
- `EVENTBRITE_TOKEN` secret wired to both jobs

Vercel auto-deploys from `master` whenever output files are committed. `Cache-Control: no-cache` headers on all `.json` and `.html` routes prevent stale data from being served.

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Configuration Reference

**`config/settings.yaml`** (Chicago defaults):

```yaml
child:
  birth_date: "2025-03-01"
  age_range_months: [0, 36]
location:
  city: Chicago
  state: IL
  zip: 60601
  home_lat: 41.8827
  home_lng: -87.6233
  max_radius_miles: 10
  timezone: America/Chicago
preferences:
  include_free_only: false   # false = show all events, flag free ones with [FREE]
  highlight_free: true
  days_ahead: 30
  exclude_keywords: [adults-only, 21+, wine, beer, cocktail]
scraping:
  cache_ttl_hours: 6
  request_delay_seconds: 1.0
  max_workers: 5
```

---

## Notes

- Personal use only — not commercial
- Polite scraping: 1s delay between requests, 6h cache TTL, `FamilyEventsAgent/1.0` User-Agent
- No external AI APIs — zero ongoing cost
- Windows 11 compatible: all paths use `pathlib.Path`, no shell scripts in hooks
