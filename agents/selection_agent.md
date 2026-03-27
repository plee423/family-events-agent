# Agent 2: Scraper Selection

## Purpose
For each source in `config/sources_{city_slug}.yaml` that has `scraper: "TBD"`, determine the correct scraper type and fill in the full config (selectors, field_map, or special fields). Update the YAML file in place.

---

## Trigger
User says: "select scrapers for [city_slug]", "analyze sources for [city_slug]", or "fill in scrapers for [file]".

---

## Scraper Types Reference

| Type | When to use | Key config fields |
|------|-------------|-------------------|
| `ical` | URL ends `.ics`, or page has `<link rel="alternate" type="text/calendar">` | just `url` |
| `bibliocommons` | URL contains `gateway.bibliocommons.com` | `library_id`, `audiences: "babies_and_toddlers"`, `max_pages: 50` |
| `tribe_events` | URL contains `/wp-json/tribe/events/` OR page scripts reference Tribe Events | `url` pointing to the `/wp-json/tribe/events/v1/events?per_page=50` endpoint |
| `tockify` | Page has `tockify.com` script OR `api.tockify.com` in network calls | `tockify_calendar: "calendarname"`, `location_name`, `location_address` |
| `chicago_aem` | Chicago.gov domain with AEM JSON endpoint | `url` pointing to AEM JSON |
| `eventbrite` | Eventbrite organizer pages | `org_ids: ["..."]`, `max_pages: 5` (already set during discovery) |
| `api` | Response Content-Type is `application/json` and contains an array of events | `field_map.events_path`, field mappings |
| `html` | Static server-rendered HTML with visible event cards | `selectors` dict |
| `browser` | JS-rendered page — soup is empty or cards are missing with `html` | same `selectors` dict as `html` |
| `needs_custom` | None of the above fits | add comment explaining why |

**Decision order (first match wins):** iCal > bibliocommons > tribe_events > tockify > eventbrite > chicago_aem > api > html > browser > needs_custom

---

## Process

### For each `scraper: "TBD"` entry in the YAML:

**Step 1: URL heuristic checks (no fetch needed)**

- URL contains `gateway.bibliocommons.com` → `bibliocommons`, extract `library_id` from the URL path
- URL ends `.ics` or contains `/ical` → `ical`
- URL contains `/wp-json/tribe/events/` → `tribe_events`
- URL is an Eventbrite API URL → `eventbrite` (already set; skip)

**Step 2: WebFetch the events page URL**

Fetch the page. Then check:

1. **Response Content-Type header**:
   - `text/calendar` → `ical`
   - `application/json` → inspect: if it's a list/dict with event data → `api`; if it's Tribe Events format → `tribe_events`

2. **HTML content checks** (in order):
   - Find `<link rel="alternate" type="text/calendar" href="...">` → `ical`, use that href as the url
   - Find `/wp-json/tribe/events/` in `<script>` tags or page source → `tribe_events`; construct url as `{site_origin}/wp-json/tribe/events/v1/events?per_page=50`
   - Find `tockify.com` in `<script src>` → `tockify`; extract calendar name from script params
   - Find `gateway.bibliocommons.com` → `bibliocommons`
   - Page is Chicago.gov with known AEM JSON pattern → `chicago_aem`

3. **If HTML with static content**: try to identify event card structure:
   - Look for repeating containers: `article`, `li`, `.event`, `[class*="event"]`, `.card`
   - Look for title: `h2 a`, `h3 a`, `[class*="title"] a`
   - Look for date: `time[datetime]`, `[class*="date"]`, `.date`
   - Look for location: `[class*="location"]`, `.venue`, `.location`
   - Look for link: the `<a>` wrapping title, or the card itself if it's an `<a>`
   - If selectors can be found → `html`

4. **If HTML but event content is absent/empty** (page uses JS rendering):
   - If the page source contains `React`, `Vue`, `Angular`, `__NEXT_DATA__`, `window.__STATE__` → `browser`
   - Try the same selectors as you would for `html` but set `scraper: "browser"`

5. **If none of the above**: `scraper: "needs_custom"` — add a YAML comment explaining what was observed

**Step 3: Write the full config entry**

Replace `scraper: "TBD"` with the determined scraper type and add all required fields.

Examples:

```yaml
# bibliocommons
- name: "LA Public Library - Events"
  org_type: "library"
  url: "https://gateway.bibliocommons.com/v2/libraries/lapl/events"
  scraper: "bibliocommons"
  library_id: "lapl"
  audiences: "babies_and_toddlers"
  max_pages: 50
  tags: ["storytime", "library", "baby", "toddler"]
  age_hint: "0-60 months"
  cost: "free"

# tribe_events
- name: "California Science Center - Events"
  org_type: "museum"
  url: "https://californiasciencecenter.org/wp-json/tribe/events/v1/events?per_page=50"
  scraper: "tribe_events"
  tags: ["science", "museum", "family", "stem"]
  age_hint: "0-60 months"

# html
- name: "Griffith Park - Family Programs"
  org_type: "parks"
  url: "https://www.laparks.org/programs/family"
  scraper: "html"
  selectors:
    event_card: "article.event, .event-listing li"
    title: "h3 a, h2 a"
    date: "time, .event-date"
    location: ".location, .venue"
    link: "h3 a, h2 a"
  tags: ["park", "outdoor", "family", "free"]
  cost: "free"

# needs_custom
- name: "The Grove - Family Events"
  org_type: "entertainment"
  url: "https://thegrovela.com/events"
  scraper: "needs_custom"
  tags: ["family", "entertainment"]
  # Custom scraper needed: React SPA, events loaded via GraphQL.
  # No iCal feed, no Tribe Events API, no static HTML cards.
```

---

## Output

Update `config/sources_{city_slug}.yaml` in place (all `TBD` entries replaced).

Print a summary when done:

```
Scraper assignment complete for {N} sources:

  #   Name                                 Scraper         Notes
  1   LA Public Library - Events           bibliocommons   auto-detected
  2   Natural History Museum               tribe_events    wp-json found in page source
  3   Griffith Park - Family Programs      html            static cards, selectors set
  4   The Grove - Family Events            needs_custom    React SPA / GraphQL

Sources needing custom scrapers: {M}
Next step: run the Coding Agent for each needs_custom entry.
Trigger: "write scraper for '[Source Name]' in {city_slug}"
```
