# CLAUDE.md — Project Instructions for family-events-agent

## Common Errors Reference

**Before planning any change and before debugging any failure, read `common_errors.md`.**
It catalogs every real mistake made during development — CI push races, artifact overwrite bugs, Eventbrite API changes, geocoding failures, filter false positives, UI download bugs, and more.
Use the Quick Checklist at the bottom of that file to identify which sections are relevant to the current task.

---

## Context Window Management

### At ~90% context: compact and reload
When the context window approaches 90% full:
1. Read `PROJECT_CONTEXT.md` (repo root) to regain full project context
2. Do NOT attempt to scroll back through the conversation — `PROJECT_CONTEXT.md` is authoritative
3. Summarize any new work done in this session into `PROJECT_CONTEXT.md` before compacting

### Update PROJECT_CONTEXT.md after every major execution
After any of these events, update the **Current State** section (and any other affected sections) of `PROJECT_CONTEXT.md`:
- A new scraper is added or modified
- A new source is added to `config/sources.yaml` or `config/sources_irvine.yaml`
- A filter is changed
- A bug is fixed that changes behavior
- A new CLI command is added
- Tests are written or updated
- The pipeline is run end-to-end and results are observed

**How to update:** Edit the relevant section(s) of `PROJECT_CONTEXT.md` — Current State, Key Files, Config, etc. Keep it precise and up-to-date so it can fully substitute for re-reading the whole conversation.

**No permission needed:** Always update `PROJECT_CONTEXT.md` immediately after work is done — do not ask the user for permission first.

**Timing:** Update immediately after each individual fix, scraper change, or run — not at the end of a session. If you fix a bug, update before moving to the next task. If you run the pipeline, update with the results before doing anything else.

---

## Project Overview (Quick Reference)

- **Purpose:** Scrape 20+ Chicago-area organizations for baby/toddler events → filter → output `.ics` for iPhone
- **Entry point:** `python agent.py run`
- **Child DOB:** 2025-03-01 | **Home:** Chicago, IL (41.8827, -87.6233) | **Radius:** 10 miles
- **Full context:** See `PROJECT_CONTEXT.md` (repo root)

---

## Web Scraping Best Practices

### Scraper selection (prefer in this order)
1. **iCal feed** (`scraper: ical`) — most reliable, structured, no parsing needed
2. **JSON API** (`scraper: api`) — structured, stable field names
3. **HTML static** (`scraper: html`) — requests + BeautifulSoup for server-rendered pages
4. **Browser** (`scraper: browser`) — Playwright headless Chromium only when JS rendering is required

Never use a browser scraper when a static HTML scraper works — it is slower and more brittle.

### Rate limiting and politeness
- Always enforce `request_delay_seconds` (default 1.0s) between requests — already in `BaseScraper`
- Cache results for `cache_ttl_hours` (default 6h) — never hammer the same site twice in a session
- Use the project User-Agent: `FamilyEventsAgent/1.0 (personal family calendar tool)`
- Do not set `max_workers` above 5 — we are a polite personal tool, not a crawler

### Retry logic
- All scrapers use `tenacity` with `stop_after_attempt(3)` and `wait_exponential(min=2, max=10)`
- On permanent failure (404, changed structure), log the error and return `[]` — never crash the whole pipeline
- Log at WARNING on retry, ERROR on final failure

### CSS selectors
- Prefer specific, stable selectors (IDs, ARIA roles, data attributes) over class names that change with redesigns
- Always test with `python agent.py test-source "Source Name"` before committing a new source
- Use `soup.select_one()` not `soup.find()` — CSS selectors are more consistent
- Fall back gracefully: if a selector finds nothing, return `[]` with a debug log, not an exception

### Date parsing
- Always use `dateutil.parser.parse(..., fuzzy=True)` — never hand-roll date parsing
- Run strings through `_clean_date_str()` first to normalize ranges and day-of-week prefixes
- If no parseable date is found, skip the event — a dateless event is useless
- Always handle both timezone-aware and naive datetimes; use `_localize()` in `ics_builder.py` before writing

### HTML scraping hygiene
- Get text with `.get_text(strip=True)` — never use `.string` (fails on nested tags)
- For links, prefer `tag.get("href")` and resolve relative URLs with `urljoin(base_url, href)`
- For `<time>` elements, check `tag.get("datetime")` before falling back to visible text
- Never trust the `<title>` tag for event titles — always use the event card's heading

### Playwright / browser scraper
- Always set `browser_timeout_seconds` (default 30) on `page.goto()`
- Wait for a known selector to appear (`page.wait_for_selector`) before extracting — never use `time.sleep()`
- Close the browser in a `finally` block — leaked Chromium processes crash Windows sessions
- Avoid screenshots or downloads in headless mode unless explicitly debugging

### iCal scraper
- Walk all `VEVENT` components; skip anything that is not `VEVENT`
- Convert `date` → `datetime` at midnight when `DTSTART` is a bare date
- Merge `CATEGORIES` from the feed into the source's `tags` list

### API scraper
- Use `field_map.events_path` dot-path navigation for nested JSON
- Always validate that the resolved path is a `list` before iterating
- Store raw cost string; use `_infer_free()` to derive `is_free`

### Security
- Never pass user-supplied strings directly into shell commands or `eval()`
- Do not store API keys or credentials in `sources.yaml` — use environment variables
- Sanitize scraped text before writing to `.ics` — strip `\r` and control characters

---

## Filter Pipeline Rules

- Run filters in order: **date window → keyword exclusion → age → cost → location → dedup → sort**
- Never reorder the pipeline — location filter (geocoding) is expensive; run it after cheap filters
- Events with no location info are **kept**, not dropped — we can't exclude them fairly
- `include_free_only: false` by default — flag free events with `[FREE]` prefix, don't hide paid ones

---

## .ics / Calendar Rules

- UIDs must be deterministic: `sha256(title|date_start|location_name|org_name)[:32]` — never use `uuid4()`
- Always include a `VTIMEZONE` component — Apple Calendar requires it
- Default `DTEND` to `DTSTART + 1 hour` when end time is unknown
- Keep `SUMMARY` ≤ 75 characters — truncate with `…` if longer
- Two `VALARM`s per event: 24h before and 2h before
- Use `SEQUENCE: 0` — increment only if updating an already-published event

---

## Code Style

- Python 3.11+; use `from __future__ import annotations` in all modules
- Type-annotate all function signatures
- Dataclasses for data structures; no plain dicts passed between modules
- `logging` over `print` everywhere except the CLI layer (`click.echo`)
- Keep modules single-responsibility — scrapers scrape, filters filter, builders build
- No hardcoded city/location strings in scraper or filter code — all location config comes from `settings.yaml`

---

## Testing

- Run tests with: `pytest tests/ -v`
- Each scraper test should mock HTTP (use `responses` or `unittest.mock`) — no live network in tests
- Each filter test should use a small handcrafted `Event` list, not real scraped data
- The `.ics` builder test should parse the output with `icalendar.Calendar.from_ical()` and assert field values

---

## Adding a New Source (checklist)

1. Open `config/sources.yaml` (Chicago) or `config/sources_irvine.yaml` (Irvine)
2. Add entry with: `name`, `org_type`, `url`, `scraper`, `selectors` (or `field_map`), `tags`, optionally `age_hint` and `cost`
3. Test: `python agent.py test-source "Source Name" --no-cache`
4. If 0 events: open DevTools, verify selectors, switch `html` → `browser` if JS-rendered
5. Run `python agent.py run --dry-run` to verify it passes all filters
6. Update `project_context.md` → Chicago Sources section

---

## Windows 11 Compatibility

- Never use `.sh` scripts in hooks or automation — use `.py` or `.bat`/`.cmd`
- Never use `${VAR}` syntax in hook command strings — use Python `%VAR%` or pass via env
- Use `Path` (pathlib) for all file paths — never string concatenation
- `_safe_echo()` in `agent.py` handles Windows cp949/cp1252 console Unicode errors — use it for all CLI output
- Playwright installs Chromium to a user-local path on Windows — run `playwright install chromium` after any fresh venv

---

## Never Make Up Data

- **Never fabricate event data, scraping results, URLs, selectors, or API field names.** If you don't know whether a selector works or an endpoint exists, say so and use `WebFetch` or `test-source` to verify it against the live site.
- **Never invent example output.** When debugging a scraper, only report what the actual HTTP response or DOM inspection reveals.
- **Never hallucinate working counts.** If a run hasn't been executed yet, say "not yet run" — never guess how many events a source will return.
- **Never construct mock or placeholder Event objects** to test the pipeline unless explicitly asked. Use cached real data or run `--no-cache` against live sources.
- If uncertain about a fact (API endpoint shape, CSS class name, JS framework), always verify with `WebFetch`, `Grep`, or `Bash` before stating it as true.

---

## City Expansion Agents

Three agent workflows exist for adding a new city. Each is documented in `agents/`. Use them when the user asks to expand to a new city or add sources.

### When to invoke each agent

| Trigger phrase | Agent file | What it does |
|---|---|---|
| "find sources for [City]" / "expand to [City]" | `agents/discovery_agent.md` | WebSearch for orgs, write `config/sources_{slug}.yaml` + `config/settings_{slug}.yaml` |
| "select scrapers for [slug]" / "analyze sources for [slug]" | `agents/selection_agent.md` | WebFetch each URL, determine scraper type, fill in selectors/field_map in the YAML |
| "write scraper for '[Name]'" / "code scraper for [URL]" | `agents/coding_agent.md` | Write `scrapers/{name}_scraper.py`, explain first, wait for approval |

### Full city expansion workflow

```
1. User: "expand to Los Angeles, CA — home: 34.05, -118.24, zip 90012, radius 15mi"
2. Run discovery_agent.md  → writes config/sources_los_angeles.yaml (scraper: "TBD")
                           → writes config/settings_los_angeles.yaml
3. Run selection_agent.md  → fills in all scraper types + selectors in sources_los_angeles.yaml
4. For each needs_custom entry: run coding_agent.md
5. User manually adds any new elif lines to agent.py get_scraper()
6. Verify: python agent.py sources --location los_angeles
           python agent.py run --location los_angeles --dry-run
```

### City slug convention

`city_slug` = lowercase city name, spaces → underscores (e.g. `los_angeles`, `san_diego`).
Used in: `config/sources_{slug}.yaml`, `config/settings_{slug}.yaml`, output filenames.

---

## Error and Fix Communication Rule (from global CLAUDE.md)

Before suggesting or applying any fix, always explain:
1. What the error is
2. The root cause
3. The exact change being made
4. Why the fix works
5. What impact it will have on the app

Do not apply any fix without this explanation first. Wait for user approval.
