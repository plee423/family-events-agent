# Agent 3: Scraper Coding

## Purpose
Write a new custom Python scraper class for a source that has `scraper: "needs_custom"` — one that doesn't fit any of the 11 existing scraper types.

---

## Trigger
User says: "write scraper for '[Source Name]'" or "code scraper for [URL]", or there are `needs_custom` entries after running the Selection Agent.

---

## Pre-flight: Follow the Error and Fix Communication Rule

Before writing any code, you MUST explain:
1. What structure the page uses (React/GraphQL, proprietary JSON API, unusual HTML, etc.)
2. The approach you'll take (which HTTP calls, how to parse the response)
3. The exact class name and file name
4. Why no existing scraper type fits
5. Any risks (fragile selectors, missing auth, pagination challenges)

Wait for user approval before writing the file.

---

## Process

### Step 1: Read existing patterns

Read these files to understand the required interface and style:
- `scrapers/base.py` — `BaseScraper` abstract class and `Event` dataclass
- `scrapers/html_scraper.py` — simplest concrete scraper (pattern to follow)
- `scrapers/tockify_scraper.py` — example of overriding `scrape()` for custom pagination

### Step 2: Investigate the target page

`WebFetch` the source's URL. For JS-heavy pages also try:
- Looking for XHR/API endpoints in inline `<script>` tags
- Checking for `window.__INITIAL_STATE__`, `__NEXT_DATA__`, or similar serialized JSON in the HTML
- Checking if the site has an undocumented `/wp-json/` or REST endpoint

Identify:
- Where the event data lives (DOM selector, JSON path, API endpoint)
- Date format used
- How pagination works (if any)
- What fields are available (title, date, location, description, url, cost)

### Step 3: Explain your approach (required — wait for approval)

Write out:
- **Page structure**: what the scraper will encounter
- **Approach**: exactly which HTTP requests, which selectors or JSON paths
- **Class name**: e.g. `GriffithScraper` → file: `scrapers/griffith_scraper.py`
- **Scraper type it extends**: almost always `BaseScraper` with `requests` or custom `scrape()` override
- **Why custom**: what rule disqualifies all 11 existing types

### Step 4: Write the scraper file

Follow these conventions exactly:

```python
"""Scraper for {Org Name} — {brief reason it needs a custom scraper}."""
from __future__ import annotations

import logging
import time
from datetime import datetime

import requests
from dateutil import parser as dateutil_parser
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event, _infer_free, _clean_date_str

logger = logging.getLogger(__name__)


class {ClassName}(BaseScraper):
    """
    {One-sentence description of what this scraper does}.

    Configure in sources_{city}.yaml:
        scraper: "{scraper_name}"
        {any custom fields required}
    """

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",  # or text/html — match the endpoint
        })

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def fetch(self, url: str) -> str:
        time.sleep(self.request_delay)
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        return resp.text

    def parse(self, content: str, source_config: dict) -> list[Event]:
        # ... implement parsing ...
        pass

    # Override scrape() only if you need custom pagination or multi-step logic
```

Rules:
- Use `dateutil_parser.parse(_clean_date_str(date_str), fuzzy=True)` for all date parsing
- Use `_infer_free(cost_hint, title, description)` for the `is_free` field
- Use `source_config.get("name", "Unknown")` for `org_name`
- Use `source_config.get("tags", [])` for tags
- Always return `[]` (not raise) on permanent fetch failure — log at ERROR level
- Never hardcode city/location strings

### Step 5: Print the factory line

After writing the file, print exactly what line to add to `agent.py`'s `get_scraper()` function:

```
Add this to get_scraper() in agent.py (after the last elif, before the else):

    elif scraper_type == "{scraper_name}":
        from scrapers.{scraper_name}_scraper import {ClassName}
        return {ClassName}(settings)
```

### Step 6: Update sources_{city_slug}.yaml

Change the entry from:
```yaml
  scraper: "needs_custom"
```
to:
```yaml
  scraper: "{scraper_name}"
  # {brief note about the custom scraper}
```

Add any required custom fields (e.g. `api_endpoint`, `calendar_id`, etc.) that the scraper reads from `source_config`.

---

## Output summary

```
Custom scraper written: scrapers/{scraper_name}_scraper.py

Class: {ClassName}
Extends: BaseScraper

Manual step required — add to agent.py get_scraper():
    elif scraper_type == "{scraper_name}":
        from scrapers.{scraper_name}_scraper import {ClassName}
        return {ClassName}(settings)

Test with:
    python agent.py test-source "{Source Name}" --location {city_slug} --no-cache
```
