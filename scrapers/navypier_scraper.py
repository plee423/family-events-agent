"""Scraper for Navy Pier events via Playwright + data-date attribute."""
from __future__ import annotations

import logging
from datetime import datetime

from bs4 import BeautifulSoup

from .base import BaseScraper, Event, _infer_free

logger = logging.getLogger(__name__)

_BASE_URL = "https://navypier.org"
_EVENTS_PAGE = f"{_BASE_URL}/pier-events/"


class NavyPierScraper(BaseScraper):
    """
    Scrapes Navy Pier events using Playwright (JS-rendered page).

    Card structure (verified 2026-03-28):
        div.event-tile
          a.layout-wrap[href="/pier-events/event-slug/"]
            p.eyebrow[data-date="YYYYMMDD"]   ← date in YYYYMMDD format
            h3.h3-style                         ← title
            span.free-tag                       ← present only for free events
    """

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.timeout_ms = int(
            float(self.scraping_cfg.get("browser_timeout_seconds", 30)) * 1000
        )

    def fetch(self, url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

        self.logger.debug("Launching headless browser for %s", url)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.user_agent, locale="en-US")
            page = context.new_page()
            try:
                page.goto(url, timeout=self.timeout_ms, wait_until="networkidle")
            except Exception as exc:
                self.logger.warning("networkidle timeout, retrying with domcontentloaded: %s", exc)
                try:
                    page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
                except Exception as exc2:
                    browser.close()
                    raise RuntimeError(f"Browser navigation failed for {url}: {exc2}") from exc2

            # Wait for event tiles to appear
            try:
                page.wait_for_selector(".event-tile", timeout=15000)
            except Exception:
                self.logger.warning("event-tile selector never appeared for %s", url)

            html = page.content()
            browser.close()
            return html

    def parse(self, content: str, source_config: dict) -> list[Event]:
        soup = BeautifulSoup(content, "lxml")
        org_name = source_config.get("name", "Navy Pier")
        tags = source_config.get("tags", [])
        age_hint = source_config.get("age_hint", "")
        cost_hint = source_config.get("cost", "")

        tiles = soup.select("div.event-tile")
        if not tiles:
            self.logger.debug("No .event-tile elements found on Navy Pier page")
            return []

        events: list[Event] = []
        for tile in tiles:
            # Title
            title_el = tile.select_one("h3.h3-style")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title:
                continue

            # Date from data-date attribute on p.eyebrow (YYYYMMDD)
            eyebrow = tile.select_one("p.eyebrow")
            if not eyebrow:
                continue
            date_attr = eyebrow.get("data-date", "")
            if not date_attr or len(date_attr) != 8:
                continue
            try:
                date_start = datetime.strptime(date_attr, "%Y%m%d")
            except ValueError:
                continue

            # Link — the direct child <a> of tile
            link_el = tile.select_one("a")
            href = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = f"{_BASE_URL}{href}"

            # Free detection — tile has span.free-tag when free
            free_tag = tile.select_one("span.free-tag")
            cost = "free" if free_tag else cost_hint
            is_free = bool(free_tag) or _infer_free(cost_hint, title, "")

            # Description
            desc_el = tile.select_one(".excerpt-wrap p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            events.append(Event(
                title=title,
                date_start=date_start,
                org_name=org_name,
                location_name="Navy Pier",
                location_address="600 E Grand Ave, Chicago, IL 60611",
                description=description,
                url=href or _EVENTS_PAGE,
                cost=cost,
                is_free=is_free,
                age_range=age_hint,
                tags=list(tags),
                source_name=source_config.get("name", org_name),
            ))

        return events
