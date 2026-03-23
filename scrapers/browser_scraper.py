"""Browser scraper using Playwright for JavaScript-rendered pages."""
from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from .base import BaseScraper, Event, parse_with_selectors

logger = logging.getLogger(__name__)


class BrowserScraper(BaseScraper):
    """
    Launches a headless Chromium browser via Playwright to render JS-heavy pages,
    then parses the fully-rendered HTML with BeautifulSoup using the same CSS
    selector config as HtmlScraper.

    Install Playwright before first use:
        pip install playwright
        playwright install chromium
    """

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.timeout_ms = int(
            float(self.scraping_cfg.get("browser_timeout_seconds", 30)) * 1000
        )

    def fetch(self, url: str, wait_selector: str = "") -> str:
        """Launch headless browser, navigate to URL, return rendered HTML.

        If wait_selector is provided (e.g. '.activity-card'), wait for that element
        to appear in the DOM before grabbing the HTML — handles pages that fire a
        second network request to load content after the initial networkidle.
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

        self.logger.debug("Launching headless browser for %s", url)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=self.user_agent,
                locale="en-US",
            )
            page = context.new_page()
            try:
                page.goto(url, timeout=self.timeout_ms, wait_until="networkidle")
            except Exception as exc:
                self.logger.warning("networkidle timeout for %s, trying domcontentloaded: %s", url, exc)
                try:
                    page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
                except Exception as exc2:
                    browser.close()
                    raise RuntimeError(f"Browser navigation failed for {url}: {exc2}") from exc2

            # If a wait_selector is specified, wait for it (handles lazy-loaded content)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=15000)
                    self.logger.debug("wait_selector %r appeared for %s", wait_selector, url)
                except Exception:
                    self.logger.warning("wait_selector %r never appeared for %s", wait_selector, url)
            else:
                page.wait_for_timeout(2000)  # small buffer for late JS

            html = page.content()
            browser.close()
            return html

    def scrape(self, source_config: dict) -> list[Event]:
        """Override to pass wait_selector from source config to fetch()."""
        url = source_config["url"]
        wait_selector = source_config.get("wait_selector", "")
        self.logger.debug("Fetching %s (wait_selector=%r)", url, wait_selector)
        content = self.fetch(url, wait_selector=wait_selector)
        events = self.parse(content, source_config)
        self.logger.info("  %s: found %d raw events", source_config["name"], len(events))
        return events

    def parse(self, content: str, source_config: dict) -> list[Event]:
        """Parse rendered HTML using shared selector logic."""
        soup = BeautifulSoup(content, "lxml")
        org_name = source_config.get("name", "Unknown")
        base_url = source_config.get("url", "")
        return parse_with_selectors(soup, source_config, org_name, base_url)
