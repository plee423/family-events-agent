# Agent 1: Source Discovery

## Purpose
Find 20–30 credible organizations in a given city that host baby/toddler/family events (ages 0–36 months). Write a draft `config/sources_{city_slug}.yaml` and a `config/settings_{city_slug}.yaml`.

---

## Trigger
User says: "find sources for [City]", "expand to [City, State]", or "add [City] sources".

Required info to collect from user before starting:
- City name + state
- Home coordinates (lat, lng)
- Zip code
- Timezone (default `America/Los_Angeles` for CA cities, `America/Chicago` for IL, etc.)
- Search radius in miles (default 15)

---

## Process

### Step 1: Search for sources by org type

Run one WebSearch per org type below. Use query pattern:
`"[city] [org_type] baby toddler storytime family events calendar"`

Org types to search (in order):
1. `library` — public library system (often Bibliocommons gateway)
2. `museum` — children's museum, science museum, art museum, natural history
3. `parks` — city parks & recreation department events
4. `zoo` — zoo, aquarium, nature center
5. `bookstore` — independent bookstore with storytime
6. `cultural_center` — cultural institute, YMCA, community center with family programs
7. `entertainment` — play cafe, children's gym, family entertainment center

For each result: note the **name**, **org website**, and look for a direct **events page URL**.

### Step 2: Verify each URL with WebFetch

For each candidate, `WebFetch` the events page URL to confirm:
- The page loads (not 404/redirect loop)
- It shows event listings (not just a generic homepage)
- Note any obvious platform signals (Bibliocommons, Tribe Events, Tockify, iCal link, etc.)

Skip any source where the events page is behind a login, paywall, or returns no event content.

### Step 3: Write config/settings_{city_slug}.yaml

Use `city_slug` = lowercase city name, spaces replaced with underscores (e.g. `los_angeles`).

Template (copy from `config/settings_irvine.yaml`, update all values):

```yaml
# {City}, {State} overrides — merged on top of settings.yaml at runtime.
# Only fields that differ from the Chicago defaults are listed here.

child:
  birth_date: "2025-03-01"
  age_range_months: [0, 36]

location:
  city: "{City}"
  state: "{State}"
  zip: "{zip}"
  home_lat: {lat}
  home_lng: {lng}
  max_radius_miles: {radius}
  timezone: "{timezone}"

output:
  filename_template: "events_{city_slug}_{start}_{end}.ics"
  json_filename: "events_{city_slug}.json"
  html_filename: "events_{city_slug}.html"
  calendar_name: "{City} Family Events"
  calendar_color: "#FF6B9D"
```

### Step 4: Write config/sources_{city_slug}.yaml

Use the verified sources. **Do not fill in scraper config yet** — use `scraper: "TBD"` as a placeholder. The Selection Agent (agents/selection_agent.md) fills in scraper details.

Structure each entry as:

```yaml
- name: "{Org Name} - {Program Type}"
  org_type: "{org_type}"
  url: "{verified_events_page_url}"
  scraper: "TBD"
  tags: ["{tag1}", "{tag2}"]          # relevant tags from: storytime, library, museum, family, baby, toddler, free, park, zoo, etc.
  age_hint: "0-60 months"
  cost: ""                             # "free" if known free; leave empty if unknown
```

Add a comment header and group by org type, following the pattern in `config/sources_irvine.yaml`.

Also add the standard Eventbrite entry for the city (always include this):

```yaml
- name: "Eventbrite - {City} Family Events"
  org_type: "eventbrite"
  url: "https://www.eventbriteapi.com/v3/events/search/"
  scraper: "eventbrite"
  keywords: "baby toddler storytime family kids infant preschool children"
  max_pages: 5
  tags: ["family", "community", "kids"]
  age_hint: "0-60 months"
```

---

## Output

- `config/settings_{city_slug}.yaml` — city settings override file
- `config/sources_{city_slug}.yaml` — draft sources (scraper fields are `"TBD"`)

After writing both files, print a summary table:

```
Discovered {N} sources for {City}, {State}:

  #   Name                                    Type           URL verified
  1   LA Public Library - Events              library        ✓
  2   Natural History Museum of LA            museum         ✓
  ...

Next step: run the Selection Agent to assign scraper types.
Trigger: "select scrapers for {city_slug}" or "analyze sources for {city_slug}"
```
