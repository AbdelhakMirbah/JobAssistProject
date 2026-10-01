"""
src/scrapers/linkedin_scraper.py
────────────────────────────────────────────────────────────────────────────────
LinkedIn job scraper using Playwright (Chromium, headless).

Scrapes the public LinkedIn Jobs search — no login required for basic listings.
Uses stealth techniques (viewport, locale, slow-mo) to reduce bot detection.

Strategy: LinkedInScraper implements BaseScraper — drop-in swappable.
"""
from __future__ import annotations

import asyncio
import random
import re

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

from src.scrapers.base_scraper import BaseScraper, ScrapedJob
from src.utils.logger import get_logger

logger = get_logger(__name__)

_SEARCH_URL = "https://www.linkedin.com/jobs/search/"


class LinkedInScraper(BaseScraper):
    """
    Scrapes public LinkedIn job listings using Playwright (headless Chromium).

    Parameters
    ----------
    headless:
        Run browser in headless mode (default True).
    slow_mo:
        Milliseconds to slow Playwright operations — reduces detection.
    timeout:
        Page navigation timeout in milliseconds.
    """

    def __init__(
        self,
        headless: bool = True,
        slow_mo: float = 150,
        timeout: int = 30_000,
    ) -> None:
        self._headless = headless
        self._slow_mo = slow_mo
        self._timeout = timeout

    @property
    def source_name(self) -> str:
        return "linkedin"

    async def scrape(
        self,
        query: str,
        location: str,
        max_results: int = 25,
    ) -> list[ScrapedJob]:
        """
        Scrape LinkedIn public job search for ``query`` in ``location``.

        Returns up to ``max_results`` ScrapedJob objects.
        """
        logger.info(
            "LinkedIn scrape: query=%r location=%r max=%d", query, location, max_results
        )
        jobs: list[ScrapedJob] = []

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(
                headless=self._headless,
                slow_mo=self._slow_mo,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context: BrowserContext = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                locale="fr-FR",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page: Page = await context.new_page()
            page.set_default_timeout(self._timeout)

            try:
                jobs = await self._run_scrape(page, query, location, max_results)
            except Exception as exc:  # noqa: BLE001
                logger.error("LinkedIn scrape failed: %s", exc, exc_info=True)
            finally:
                await browser.close()

        logger.info("LinkedIn returned %d jobs", len(jobs))
        return jobs

    async def _run_scrape(
        self,
        page: Page,
        query: str,
        location: str,
        max_results: int,
    ) -> list[ScrapedJob]:
        """Core scraping logic — navigate, scroll, and parse job cards."""
        params = (
            f"?keywords={query.replace(' ', '%20')}"
            f"&location={location.replace(' ', '%20')}"
            f"&f_TPR=r604800"   # last 7 days
        )
        url = _SEARCH_URL + params
        logger.debug("LinkedIn navigating to: %s", url)
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(1.5, 2.5))

        jobs: list[ScrapedJob] = []
        seen_urls: set[str] = set()
        scroll_attempts = 0
        max_scrolls = max(8, max_results // 3)

        while len(jobs) < max_results and scroll_attempts < max_scrolls:
            # Parse currently visible cards
            new_jobs = await self._parse_visible_cards(page, seen_urls)
            jobs.extend(new_jobs)

            if len(jobs) >= max_results:
                break

            # Scroll to load more
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(1.0, 2.0))

            # Click "See more jobs" button if present
            see_more = page.locator(
                "button.infinite-scroller__show-more-button, "
                "button[aria-label*='See more'], "
                "button[data-tracking-control-name='public_jobs_jobs-search-bar_see-all-jobs']"
            )
            if await see_more.count() > 0:
                try:
                    await see_more.first.click()
                    await asyncio.sleep(random.uniform(1.0, 2.0))
                except Exception:  # noqa: BLE001
                    pass

            scroll_attempts += 1

        return jobs[:max_results]

    async def _parse_visible_cards(
        self,
        page: Page,
        seen_urls: set[str],
    ) -> list[ScrapedJob]:
        """Parse all currently visible job cards on the page."""
        cards = await page.locator(
            "ul.jobs-search__results-list li, "
            "div.base-card, "
            "li.job-search-card"
        ).all()

        jobs = []
        for card in cards:
            try:
                job = await self._parse_card(card, seen_urls)
                if job:
                    jobs.append(job)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to parse LinkedIn card", exc_info=True)

        return jobs

    async def _parse_card(self, card, seen_urls: set[str]) -> ScrapedJob | None:
        """Extract job data from a single LinkedIn card element."""
        # Title
        title_el = card.locator(
            "h3.base-search-card__title, "
            "h3.job-search-card__title, "
            "a.base-card__full-link span"
        ).first
        title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else None
        if not title:
            return None

        # Company
        company_el = card.locator(
            "h4.base-search-card__subtitle, "
            "a.hidden-nested-link, "
            "span.job-search-card__company-name"
        ).first
        company = (
            (await company_el.inner_text()).strip()
            if await company_el.count() > 0
            else "Unknown"
        )

        # Location
        loc_el = card.locator(
            "span.job-search-card__location, "
            "span.base-search-card__metadata"
        ).first
        location = (await loc_el.inner_text()).strip() if await loc_el.count() > 0 else ""

        # URL
        link_el = card.locator("a.base-card__full-link, a.job-search-card__list-date-img").first
        href = await link_el.get_attribute("href") if await link_el.count() > 0 else None
        if not href:
            return None

        # Normalise URL — strip tracking params
        url = re.sub(r"\?.*$", "", href.split("?")[0])
        if url in seen_urls:
            return None
        seen_urls.add(url)

        return ScrapedJob(
            title=title,
            company=company,
            location=location,
            url=url,
            source=self.source_name,
            description="",  # Full description fetched separately if needed
        )
