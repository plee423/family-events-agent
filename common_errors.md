# Common Errors — family-events-agent

> Read this before planning any change and before debugging any failure.
> Each entry records a real mistake made during development, its root cause, and the fix applied.

---

## CI / GitHub Actions

### 1. Git push race condition in `commit-outputs`
**Symptom:** Push fails intermittently; "unstaged changes" error during rebase; rebase conflicts on output files when two runs fire close together.
**Root cause:** Original pattern committed → push → on failure: pull --rebase. The window between push failure and pull was ~2 minutes, long enough for a second run to push. Also, `git pull --rebase` failed with "unstaged changes" when the working tree was dirty.
**Fix:** Always `git fetch origin master` → `git rebase -X theirs origin/master` → `git push` in a retry loop. The failure window is now milliseconds (between rebase and push), not minutes. Also add `concurrency: group: scrape-events, cancel-in-progress: true` to prevent two runs racing.
**Also requires:** `actions/checkout@v4` with `fetch-depth: 0` — shallow clones can break rebase in edge cases.
**Commit:** `fdf01a6`

### 2. Irvine artifact overwrote Chicago artifact
**Symptom:** `commit-outputs` job showed no changes for Chicago files even after a successful scrape.
**Root cause:** Both Chicago and Irvine scrape jobs uploaded their entire `output/` directory. The Irvine artifact (uploaded second, containing the stale `events_chicago.json` from checkout) overwrote the fresh Chicago artifact when downloaded.
**Fix:** Each job uploads ONLY the files it produced (city-scoped glob). Download path changed from `output/` to `.` (repo root) so artifact paths like `output/events_chicago.json` restore to the correct location.
**Commit:** `7fd6483`

### 3. `commit-outputs` blocked when one scrape job fails
**Symptom:** Chicago output never committed when the Irvine scrape job errored out.
**Root cause:** `commit-outputs` `needs: [scrape-chicago, scrape-irvine]` defaults to only running when all dependencies succeed.
**Fix:** Set `if: ${{ !cancelled() }}` on `commit-outputs`. Add `continue-on-error: true` to the Irvine artifact download step so a missing Irvine artifact is non-fatal.
**Commit:** `f7c2988`

### 4. Artifact not landing in expected directory
**Symptom:** `git add public/ output/` in `commit-outputs` found nothing to stage despite successful download.
**Root cause:** `download-artifact@v4` with `path: output/` extracts to `output/output/events_chicago.json` when the artifact itself contains the `output/` prefix.
**Fix:** Each scrape job copies files to `public/` before upload. Artifact contains both `public/` and `output/` files at their correct repo-relative paths. Download with `path: .` lands them where `git add` expects.
**Commit:** `778508b`

---

## Vercel / Static Site

### 5. Vercel deployment error
**Symptom:** Vercel failed to deploy or served a blank page.
**Root cause:** Used `version: 2`, `public: true`, and a `rewrites` block — Vercel's newer CLI ignores `version` and the rewrite rule caused routing conflicts for a pure static site.
**Fix:** Remove `version`, `public`, and `rewrites`. Use only `framework: null`, `outputDirectory: "public"`, and null build/install/dev commands.
**Commit:** `bf03ad5`

### 6. Browser serving stale event data after nightly scrape
**Symptom:** Users see outdated events even after CI pushes a fresh JSON.
**Root cause:** No `Cache-Control` headers — Vercel CDN and browser both cache `*.json` and `events_*.html` files aggressively.
**Fix:** Add `Cache-Control: no-cache, must-revalidate` headers for all `*.json` and `events_*.html` routes in `vercel.json`.
**Session:** 9

---

## Scrapers

### 7. Eventbrite `/v3/events/search/` returns 404
**Symptom:** Eventbrite scraper returns 0 events; API responds 404.
**Root cause:** `/v3/events/search/` endpoint was shut down in February 2020. All requests return 404 regardless of token validity.
**Fix:** Use `/v3/organizers/{id}/events/?expand=venue,ticket_classes` — this endpoint is public and works with a free developer token. **Do not use** `/v3/organizations/{id}/events/` (different path, requires elevated auth, also returns 404 for most tokens).
**Commit:** `80ff954`

### 8. Eventbrite returns 400 for query params
**Symptom:** API returns 400 Bad Request when passing `status`, `page_size`, or `start_date.range_start`.
**Root cause:** The `/v3/organizers/{id}/events/` endpoint only accepts `expand` as a query param. All other filtering params are rejected.
**Fix:** Accept up to 50 events per page (API default). Filter past events client-side in Python. Paginate using `pagination.continuation` token.
**Session:** 6

### 9. Eventbrite returns 0 upcoming events (pagination issue)
**Symptom:** Org has many events but 0 pass the "future events only" filter.
**Root cause:** API returns events in ascending date order (oldest first). Orgs with a large event history fill all 50 slots on page 1 with past events. Without pagination, all events are dropped as past.
**Fix:** Paginate using `pagination.continuation` token in `_fetch_org_events`, up to `max_pages` (configurable, default 5). Stop when `has_more_items=False` or continuation is absent.
**Commit:** `a8423fe` → confirmed fix in session 9

### 10. Eventbrite online events treated as location-based
**Symptom:** Eventbrite virtual events show `lat=0.0`, fail geocoding, or get dropped by the location filter.
**Root cause:** `is_online_event: true` events return a venue with `latitude: 0.0` / `longitude: 0.0`. The location filter tried to geocode the venue address (often "Online") and computed a ~8,000-mile distance from Chicago, dropping the event.
**Fix:** Detect `is_online_event: True` or `lat == 0.0` sentinel in `eventbrite_scraper.py`; set `neighborhood="Virtual"` and leave `lat/lng = None`. In `location_filter.py`, add `_is_virtual()` helper that checks venue name/address for "online"/"virtual"/"zoom"/"webinar"/"livestream" — virtual events skip geocoding and distance check entirely.
**Commit:** `59635c7`

### 11. CPL branch geocoding returns wrong location
**Symptom:** CPL events from certain branches (e.g. Blackstone) show wrong neighborhood.
**Root cause:** Bibliocommons `/branches` API returns no address data. `location_filter.py` fell back to geocoding the bare branch name (e.g. "Blackstone, Chicago, IL"). Nominatim resolved "Blackstone" to the Blackstone Hotel in The Loop instead of the Blackstone Branch Library in Hyde Park.
**Fix:** Add `_CPL_BRANCH_COORDS` lookup table (81 branches, coordinates from City of Chicago Open Data portal dataset `x8fc-8rcq`) to `bibliocommons_scraper.py`. `_parse_event` sets `location_lat/lng` and `location_address` directly from this table, bypassing Nominatim entirely.
**Also:** Remove the stale wrong geocode cache entry from `cache/geocode_cache.json` after applying the fix.
**Commit:** `85836b8`

### 12. Empty-result runs cached and poisoning subsequent runs
**Symptom:** After running without `EVENTBRITE_TOKEN`, all subsequent cached runs also returned 0 Eventbrite events.
**Root cause:** `agent.py` cached every scrape result including 0-event results. A run without the API token wrote an empty cache entry, which was served to all subsequent runs within the 6h TTL.
**Fix:** Only write cache when `events` is non-empty: `if use_cache and events: cache.write(...)`.
**Session:** 8

---

## Filters

### 13. Age filter: `"family"` keyword caused false positives
**Symptom:** All Navy Pier events passed the age filter even though they were adult entertainment events.
**Root cause:** `"family"` was in `BABY_KEYWORDS`. Navy Pier source tags include `"family"` on all events, so every event matched.
**Fix:** Move `"family"` to `WEAK_BABY_KEYWORDS` (a separate set used only for `children_only=True` sources). Introduce `children_only` source-level flag: sources marked `children_only: false` must have an explicit baby/toddler keyword to pass; no-age-info events from those sources are rejected by default.
**Commit:** `80ff954`

### 14. Age filter: substring false positives
**Symptom:** Events with age ranges like "10-20 months" matched the keyword `"0-2"`. Events for "sidekicks" matched the keyword `"kids"`.
**Root cause:** String `in` operator matches substrings, not whole words.
**Fix:** Use `re.search(r"\b" + re.escape(kw) + r"\b", text)` for all keyword matching in `age_filter.py`.
**Commit:** `80ff954`

### 15. Cost filter: `_infer_free` incorrectly tagged paid events as free
**Symptom:** Field Museum events were tagged `[FREE]` even though admission is paid.
**Root cause:** `cost: ""` (empty string) in `sources.yaml` meant `_infer_free` found no paid signal and defaulted to free.
**Fix:** Set `cost: "paid admission"` for Field Museum, CCM, and other paid-admission sources in `sources.yaml`. Add `"paid admission"` to `paid_overrides` in `_infer_free`.
**Session:** 8

### 16. Cost filter: event descriptions override source-level paid cost
**Symptom:** CCM events were tagged `[FREE]` because event descriptions contained phrases like "free for all families", overriding the `cost: "paid admission"` source setting.
**Root cause:** `_re_evaluate_free` scanned the full description for free phrases without respecting the source-level cost signal.
**Fix:** Add Step 0 to `_re_evaluate_free`: if `event.cost` contains `"paid admission"`, only check event TITLE (not description) for strong-free phrases. This prevents description copy from overriding a known paid-admission source.
**Session:** 9

---

## Web UI (`public/index.html`)

### 17. "Add to Calendar" button downloaded 0-byte file
**Symptom:** Clicking "Add to Calendar" on a single event produced an empty or failed download in Firefox/Safari.
**Root cause 1:** Anchor element was not appended to the DOM before `.click()` — Firefox/Safari require the anchor to be in the document.
**Root cause 2:** `URL.revokeObjectURL()` was called synchronously after `.click()`, before the download could start.
**Fix:** Append anchor to `document.body` before `.click()`; call `URL.revokeObjectURL()` inside a `setTimeout(..., 2000)`.
**Session:** 8

### 18. Distance shown in event cards (confusing)
**Symptom:** Every event card showed a distance badge (e.g. "2.3 mi") which confused users since most events are clustered in the same area.
**Root cause:** Distance was rendered unconditionally for all events in `renderCard()`.
**Fix:** Remove the distance meta item from the card render loop in `public/index.html`.
**Commit:** `aba7db2`

### 19. Neighborhood filter buttons not showing
**Symptom:** Neighborhood filter bar was empty or hidden even when events had neighborhood values.
**Root cause:** Neighborhood buttons were hardcoded rather than dynamically populated; events loaded asynchronously after the filter bar rendered.
**Fix:** Populate neighborhood filter buttons dynamically from `event.neighborhood` values after data loads. Hide the filter bar when no neighborhoods are present.
**Session:** 8–9

### 20. Filter toggle button styling missing
**Symptom:** Filter toggle button (#filterToggleBtn) appeared unstyled or blended into the header.
**Root cause:** No CSS rule targeted `#filterToggleBtn` specifically; it inherited default button styles.
**Fix:** Add explicit `#filterToggleBtn` CSS rule with white background, brand color text, and hover state.
**Commit:** `088ef5d`

---

## Data / Output

### 21. CCM event links pointing to 404
**Symptom:** All Chicago Children's Museum events linked to a dead page.
**Root cause:** `website` field in `sources.yaml` pointed to an old URL that no longer exists.
**Fix:** Change CCM `website` to `https://www.chicagochildrensmuseum.org/program-calendar`.
**Session:** 8

### 22. Categories missing / displayed incorrectly after initial implementation
**Symptom:** After adding `category_assigner.py`, some events showed wrong or missing categories. Distance was being double-displayed.
**Root cause:** `renderCard()` in `index.html` still had the old distance badge line; category field was not wired through `json_builder.py` and `ics_builder.py`.
**Fix:** Wire `category` field through all builders. Remove the stray distance line in `renderCard()`. Refine category keyword rules in `category_assigner.py`.
**Commits:** `0a97904`, `aba7db2`

---

## Scraper Selectors

### 23. CSS selector verified against static page returns 0 results on live site (JS-rendered)
**Symptom:** Selectors that look correct based on View Source or a static fetch return 0 events.
**Root cause:** Page is rendered by JavaScript (React, Next.js, etc.) — the HTML seen by `requests.get()` contains empty placeholder containers, not actual event data. Static HTML selectors find nothing.
**Fix:** Check if page needs JS rendering. If `requests.get()` returns markup with empty containers (e.g. `<div id="root"></div>`, `<div class="event-grid"></div>` with no children), switch to `scraper: browser` (Playwright). Also check whether the site uses a JSON data endpoint (see error 25 below) — that's even better than browser scraping.
**Example:** Field Museum — static fetch returned empty `div.event-item` containers; Playwright rendered them but events were actually in `__NEXT_DATA__` JSON.
**Session:** 11

### 24. Selectors verified by WebFetch agent are unreliable
**Symptom:** Selectors suggested by a WebFetch agent return 0 events when run against the live site.
**Root cause:** The WebFetch tool returns an AI-synthesized summary of the page, not raw HTML. The agent can hallucinate class names, element structures, and attribute names that don't exist. Multiple agents in session 11 returned plausible-looking but wrong selectors for Field Museum, NMMA, and Navy Pier.
**Fix:** Never trust WebFetch agent HTML descriptions for selector discovery. Instead:
1. Run a Python Playwright script to fetch the real rendered HTML and inspect it directly.
2. Use `page.query_selector_all()` + `.evaluate("el => el.outerHTML")` to see actual markup.
3. Only write selectors based on real HTML you have seen in raw form.
**Session:** 11

### 25. Site redesign invalidates all existing selectors silently
**Symptom:** Source was working, then returns 0 events with no error — scraper runs successfully but finds no cards.
**Root cause:** The site was redesigned and class names, element types, or page structure changed. Old selectors match nothing in the new DOM.
**Examples from session 11:**
- Navy Pier: `article.fav-card` → `div.event-tile` (complete redesign of event listing)
- NMMA: `ul li` → `a.block.group` (headless CMS migration changed card structure)
**Fix:** When a previously working source returns 0, immediately re-inspect the live HTML (Playwright script) rather than assuming the selectors are still valid. Don't try to "fix" selectors based on the old structure — fetch and read the new structure from scratch.
**Session:** 11

### 26. Events embedded in `__NEXT_DATA__` JSON, not in DOM
**Symptom:** Browser scraper returns 0 events even after Playwright renders the page correctly; DOM inspection shows no repeating event card elements.
**Root cause:** Next.js apps sometimes pre-serialize all page data into a `<script id="__NEXT_DATA__" type="application/json">` tag. The React hydration process renders events client-side from this JSON, but the rendered elements are in Shadow DOM or dynamically inserted after Playwright's networkidle fires.
**Fix:** Check for `__NEXT_DATA__` first: `re.search(r'<script id="__NEXT_DATA__".*?>(.*?)</script>', html, re.DOTALL)`. If present, parse the JSON and navigate the `props.pageProps` tree to find the events list. No Playwright needed — plain `requests.get()` retrieves this JSON.
**Example:** Field Museum — 64 events in `props.pageProps.allEvents`. Each event has `title`, `start`/`end` (ISO8601), `slug`, `eventSeries.slug`, `description` (HTML), `ticketing`, `ageGroups`, `audienceTags`.
**Session:** 11

### 27. Date stored as non-standard attribute (`data-date`, not `datetime`)
**Symptom:** `parse_with_selectors` finds the date element but can't extract a parseable date string — returns `""`, event is skipped.
**Root cause:** `parse_with_selectors` only checks `date_el.get("datetime")` (standard `<time>` attribute) then falls back to visible text. Some sites store the date in a custom `data-date` attribute (e.g. Navy Pier: `<p class="eyebrow" data-date="20260328">`). The visible text ("Today, 12:00 PM") is not parseable for future events.
**Fix:** When a site uses a custom `data-*` attribute for dates, write a custom scraper that reads the attribute directly (e.g. `el.get("data-date")`). Don't try to wedge it into `parse_with_selectors` — that function only reads `datetime` and text content.
**Example:** Navy Pier `p.eyebrow[data-date]` → `datetime.strptime(date_attr, "%Y%m%d")`.
**Session:** 11

---

## CLI / Console

### 28. `click.echo()` in `test_source` crashes on Korean Windows (cp949 locale)
**Symptom:** `python agent.py test-source "..."` raises `UnicodeEncodeError: 'cp949' codec can't encode character` when an event title contains non-ASCII characters (e.g. Spanish accents, em-dashes).
**Root cause:** Windows console with Korean locale (cp949) can't encode many Unicode characters. `click.echo()` uses the system codec directly.
**Fix:** Replace `click.echo()` with `_safe_echo()` in the `test_source` command. `_safe_echo()` already handles this via `errors='replace'` or explicit UTF-8 wrapping.
**Session:** 11

---

## Quick Checklist Before Planning

- [ ] Does this touch CI? → Check errors 1–4 (push race, artifact scope, job dependencies, directory layout)
- [ ] Does this touch Vercel/static hosting? → Check errors 5–6 (config, cache headers)
- [ ] Does this add or change a scraper? → Check errors 7–12 (Eventbrite API, geocoding, caching), 23–27 (selectors, JS rendering, __NEXT_DATA__, data-date)
- [ ] Does this touch filters? → Check errors 13–16 (keyword matching, cost logic)
- [ ] Does this touch the web UI? → Check errors 17–20 (download button, distance display, neighborhood filter)
- [ ] Does this touch output builders or data fields? → Check errors 21–22 (broken links, field wiring)
- [ ] Does this touch the CLI? → Check error 28 (cp949 encoding)
