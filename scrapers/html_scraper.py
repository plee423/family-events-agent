"""HTML scraper using requests + BeautifulSoup for static pages."""
from __future__ import annotations

import time
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from .base import BaseScraper, Event, parse_with_selectors

logger = logging.getLogger(__name__)


class HtmlScraper(BaseScraper):
    """
    Fetches pages with requests and parses with BeautifulSoup.
    Uses CSS selectors from the source config.
    """

    def __init__(self, settings: dict):
        super().__init__(settings)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def fetch(self, url: str) -> str:
        """Fetch URL with retries. Returns HTML text."""
        time.sleep(self.request_delay)
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        return resp.text

    def parse(self, content: str, source_config: dict) -> list[Event]:
        """Parse HTML using CSS selectors from source config."""
        soup = BeautifulSoup(content, "lxml")
        org_name = source_config.get("name", "Unknown")
        base_url = source_config.get("url", "")
        return parse_with_selectors(soup, source_config, org_name, base_url)
