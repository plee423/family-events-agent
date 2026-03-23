# Family Events Agent

Automatically discovers free and family-friendly events for babies and toddlers from Chicago-area organizations, filters them, and outputs a `.ics` calendar file that imports directly into iPhone/Apple Calendar.

**The problem it solves:** Instead of manually checking 15+ organization websites every week, run one command and get a ready-to-import calendar.

---

## Quick Start

### 1. Install dependencies

```bash
cd family-events-agent
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
- Adjust `max_radius_miles` if needed
- Set `days_ahead` (default: 30)

### 3. Run it

```bash
python agent.py run
```

### 4. Import the .ics file

The calendar file is saved to `output/family_events_YYYY-MM-DD_YYYY-MM-DD.ics`.

**iPhone import options:**
- **AirDrop**: AirDrop the file from your computer to your phone → tap "Add to Calendar"
- **Email**: Email the file to yourself → tap the attachment in Mail app
- **Files app**: Save to iCloud Drive, tap the file → "Add to Calendar"

---

## CLI Commands

```bash
# Scrape all sources, generate .ics
python agent.py run

# Preview events without generating .ics
python agent.py run --dry-run

# Scrape specific sources only
python agent.py run --sources "Chicago Public Library" "Lincoln Park Zoo"

# Force re-scrape (ignore cache)
python agent.py run --no-cache

# Use alternate location config (see config/sources_irvine.yaml)
python agent.py run --location irvine

# List all configured sources
python agent.py sources

# Test a single source (great for debugging)
python agent.py test-source "Chicago Public Library"

# Clear cached scrape data
python agent.py clear-cache

# Verbose output (for debugging)
python agent.py -v run
```

---

## Configured Sources (Chicago)

### Libraries
| Source | Type | Cost |
|--------|------|------|
| Chicago Public Library — Events | library | Free |
| Chicago Public Library — Harold Washington | library | Free |
| Chicago Public Library — Near North | library | Free |

### Museums
| Source | Type | Cost |
|--------|------|------|
| Field Museum | museum | Free (IL residents) |
| Shedd Aquarium | museum | Free (Chicago residents) |
| Museum of Science and Industry | museum | Free (IL residents) |
| Art Institute of Chicago | museum | Free (IL residents under 14) |
| Chicago Children's Museum | museum | Free first Sunday (Chicago residents) |
| Chicago History Museum | museum | Free (IL residents) |
| National Museum of Mexican Art | museum | Always free |
| Peggy Notebaert Nature Museum | museum | Free (certain days) |

### Parks & Recreation
| Source | Type | Cost |
|--------|------|------|
| Chicago Park District — Toddler Programs | parks | Varies |
| Chicago Park District — Baby Programs | parks | Varies |
| Maggie Daley Park | parks | Free |
| Millennium Park | parks | Free |

### Other
| Source | Type | Cost |
|--------|------|------|
| Lincoln Park Zoo | zoo | Always free |
| Chicago Cultural Center | cultural | Always free |
| Navy Pier | entertainment | Varies |
| The Book Cellar | bookstore | Free |
| Volumes Bookcafe | bookstore | Free |

---

## How It Works

```
sources.yaml → Scrapers → Raw Events
                              ↓
                         Age Filter      (keeps baby/toddler events)
                              ↓
                         Cost Filter     (flags free events with [FREE])
                              ↓
                         Location Filter (removes events > 10 miles away)
                              ↓
                         Dedup Filter    (removes duplicates across sources)
                              ↓
                         .ics Builder    (generates iPhone-compatible calendar)
```

### Scraper types
- **html** — requests + BeautifulSoup for static pages
- **browser** — Playwright headless Chromium for JavaScript-rendered pages
- **ical** — parses `.ics` feeds directly (most reliable)
- **api** — fetches JSON from public API endpoints

### Caching
Scraped data is cached in `cache/` for 6 hours (configurable). This prevents hammering
organization websites and speeds up repeated runs. Use `--no-cache` to bypass.

### iPhone Compatibility
The generated `.ics` file is specifically designed for Apple Calendar:
- Includes a `VTIMEZONE` component for proper timezone handling
- Uses stable UIDs (hash of title + date + location) so re-importing doesn't create duplicates
- Includes two VALARM reminders: 24 hours before and 2 hours before each event
- `SEQUENCE: 0` so updates to existing events are recognized

---

## Adding a New Source

1. Open `config/sources.yaml`
2. Add a new entry:

```yaml
- name: "My New Source"
  org_type: "library"          # library, museum, parks, zoo, bookstore, etc.
  url: "https://example.org/events"
  scraper: "html"              # html, browser, ical, or api
  selectors:
    event_card: ".event-item"   # CSS selector for each event container
    title: "h2.event-name"
    date: ".event-date"
    time: ".event-time"         # optional, separate time element
    location: ".venue-name"
    link: "a.event-link"
    description: ".event-desc"
  tags: ["family", "kids"]
  age_hint: "0-36 months"      # optional
  cost: "free"                 # optional hint
```

3. Test it: `python agent.py test-source "My New Source"`

**Tip:** Use browser devtools to find the right CSS selectors. If `requests` returns empty
content (JS-rendered page), switch to `scraper: "browser"`.

---

## Moving to a New City

The system has zero hardcoded city references. To switch cities:

1. Create `config/sources_[city].yaml` with local sources
2. Update `config/settings.yaml` with new `home_lat`, `home_lng`, `zip`, `city`, and `timezone`
3. Run: `python agent.py run --location [city]`

Irvine, CA stubs are already in `config/sources_irvine.yaml`.

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Future Ideas

- **Daily cron + auto-email**: Schedule `agent.py run` daily via Task Scheduler (Windows) or cron (Mac/Linux), then email the `.ics` to your wife automatically. The stable UIDs mean she can import the same calendar weekly and it won't create duplicate events.
- **Weekly digest email**: Instead of a raw `.ics`, generate an HTML email summary of this week's events.
- **iCloud push**: Use the iCloud CalDAV API to push events directly to a shared calendar.
- **More source types**: Eventbrite API, Meetup API, Google Calendar embed scraper.
- **SMS/text alerts**: Notify about tomorrow's free events via Twilio.

---

## Notes

- This tool is for personal family use only — not commercial
- Respects rate limits: 1-second delay between requests, 6-hour cache TTL
- Uses a polite User-Agent: `FamilyEventsAgent/1.0 (personal family calendar tool)`
- All scraping is local — no external AI APIs, zero ongoing cost
