"""Playwright-based scraper.  No domain restrictions.  Truncates at 8 k chars.

Browser mode (resolved at construction time):
  - BROWSER_CDP_URL is set  →  connect to a remote Chrome via CDP (k8s / compose sidecar)
  - otherwise               →  launch Chromium locally (local dev without sidecar)
"""

from __future__ import annotations

import logging
import os

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

_MAX_CHARS = 8000


class BrowserTool:
    def __init__(self) -> None:
        self._cdp_url: str | None = os.getenv("BROWSER_CDP_URL")
        if self._cdp_url:
            logger.info("BrowserTool: will connect to remote CDP at %s", self._cdp_url)
        else:
            logger.info("BrowserTool: will launch chromium locally")

    async def scrape(self, url: str) -> str:
        """Scrape visible text from *url*.  Truncates at 8 k chars."""
        async with async_playwright() as p:
            if self._cdp_url:
                logger.info("connecting to remote browser for %s", url)
                browser = await p.chromium.connect_over_cdp(self._cdp_url)
            else:
                logger.info("launching local chromium for %s", url)
                browser = await p.chromium.launch(headless=True)

            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=30_000)
                logger.info("page load succeeded for %s (status %s)", url, page.url)
            except Exception as exc:
                logger.warning("page load failed for %s: %s", url, exc)
                raise
            text = await page.inner_text("body")

            # only close if we launched it; remote browsers stay alive
            if not self._cdp_url:
                await browser.close()

        truncated = len(text) > _MAX_CHARS
        logger.info("got %d chars%s", len(text), " (truncated)" if truncated else "")
        return text[:_MAX_CHARS]
