"""
src/scrapers/indeed_scraper.py
────────────────────────────────────────────────────────────────────────────────
Indeed job scraper — uses Playwright (Chromium, headless) to bypass bot
detection. Indeed blocks raw HTTP requests (403); a real browser session
works reliably.

Parses the public Indeed job search results page.
Strategy: IndeedScraper implements BaseScraper — drop-in swappable.
"""
from __future__ import annotations

import asyncio
import random
import re
from urllib.parse import quote_plus

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from src.scrapers.base_scraper import BaseScraper, ScrapedJob
from src.utils.logger import get_logger

logger = get_logger(__name__)

_SEARCH_URL = "https://fr.indeed.com/jobs"


class IndeedScraper(BaseScraper):
    """
    Scrapes fr.indeed.com using Playwright headless Chromium.

    Parameters
    ----------
    headless:
        Run browser invisibly (default True).
    slow_mo:
        Milliseconds to slow Playwright — helps avoid detection.
    timeout:
        Page load timeout in milliseconds.
    delay_range:
        (min, max) seconds to pause between pages.
    """

    def __init__(
        self,
        headless: bool = True,
        slow_mo: float = 120,
        timeout: int = 25_000,
        delay_range: tuple[float, float] = (1.5, 3.0),
    ) -> None:
        self._headless = headless
        self._slow_mo = slow_mo
        self._timeout = timeout
        self._delay_range = delay_range

    @property
    def source_name(self) -> str:
        return "indeed"

    async def scrape(
        self,
        query: str,
        location: str,
        max_results: int = 25,
    ) -> list[ScrapedJob]:
        """
        Scrape Indeed for jobs matching ``query`` in ``location``.

        Returns up to ``max_results`` ScrapedJob objects.
        Returns empty list on error (Reliability — never raises).
        """
        logger.info(
            "Indeed scrape: query=%r location=%r max=%d", query, location, max_results
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
                viewport={"width": 1280, "height": 800},
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
                logger.error("Indeed scrape failed: %s", exc, exc_info=True)
            finally:
                await browser.close()

        logger.info("Indeed returned %d jobs", len(jobs))
        return jobs

    async def _run_scrape(
        self, page: Page, query: str, location: str, max_results: int
    ) -> list[ScrapedJob]:
        """Navigate to Indeed, handle cookie consent, and scrape job cards."""
        url = (
            f"{_SEARCH_URL}?q={quote_plus(query)}"
            f"&l={quote_plus(location)}"
            f"&sort=date"
        )
        logger.debug("Indeed navigating to: %s", url)
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(1.5, 2.5))

        # Dismiss cookie banner if present
        for selector in [
            "button#onetrust-accept-btn-handler",
            "button[id*='accept']",
            "button:has-text('Accepter')",
            "button:has-text('Accept')",
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.8)
                    break
            except Exception:  # noqa: BLE001
                pass

        jobs: list[ScrapedJob] = []
        seen_urls: set[str] = set()
        page_num = 0

        while len(jobs) < max_results:
            new_jobs = await self._parse_current_page(page, seen_urls)
            jobs.extend(new_jobs)
            logger.debug("Indeed page %d → %d jobs collected so far", page_num, len(jobs))

            if len(jobs) >= max_results:
                break

            # Try to go to next page
            next_btn = page.locator("a[data-testid='pagination-page-next'], a[aria-label='Suivant']").first
            if await next_btn.count() == 0:
                logger.info("Indeed: no more pages")
                break

            await next_btn.click()
            await asyncio.sleep(random.uniform(*self._delay_range))
            page_num += 1

        return jobs[:max_results]

    async def _parse_current_page(
        self, page: Page, seen_urls: set[str]
    ) -> list[ScrapedJob]:
        """Parse all job cards visible on the current page."""
        # Wait for cards to load
        try:
            await page.wait_for_selector(
                "div.job_seen_beacon, div.tapItem, li.css-5lfssm",
                timeout=8000,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Indeed: job cards did not appear — page may be blocked")
            return []

        cards = await page.locator(
            "div.job_seen_beacon, div.tapItem, li.css-5lfssm"
        ).all()

        jobs = []
        for card in cards:
            try:
                job = await self._parse_card(card, seen_urls)
                if job:
                    jobs.append(job)
            except Exception:  # noqa: BLE001
                logger.debug("Indeed card parse error", exc_info=True)

        return jobs

    async def _parse_card(self, card, seen_urls: set[str]) -> ScrapedJob | None:
        """Extract fields from a single Indeed card element."""
        # Title
        title_el = card.locator("h2.jobTitle span, [data-testid='job-title'], h2 a span").first
        title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else None
        if not title or title.lower() in ("new", "nouveau"):
            # Try alternate title selector
            alt = card.locator("span[title]").first
            title = (await alt.inner_text()).strip() if await alt.count() > 0 else None
        if not title:
            return None

        # Company
        company_el = card.locator(
            "[data-testid='company-name'], span.companyName, a.companyOverviewLink"
        ).first
        company = (
            (await company_el.inner_text()).strip()
            if await company_el.count() > 0
            else "Unknown"
        )

        # Location
        loc_el = card.locator("[data-testid='text-location'], div.companyLocation").first
        location = (await loc_el.inner_text()).strip() if await loc_el.count() > 0 else ""

        # URL
        link_el = card.locator("h2.jobTitle a, a[data-jk]").first
        if await link_el.count() == 0:
            return None
        href = await link_el.get_attribute("href") or ""
        job_id_match = re.search(r"jk=([a-z0-9]+)", href)
        job_id = job_id_match.group(1) if job_id_match else None

        url = (
            f"https://fr.indeed.com/viewjob?jk={job_id}"
            if job_id
            else f"https://fr.indeed.com{href}".split("?")[0]
        )

        if url in seen_urls:
            return None
        seen_urls.add(url)

        # Description snippet
        desc_el = card.locator("div.job-snippet, ul.jobsearch-ResultsList").first
        description = (await desc_el.inner_text()).strip() if await desc_el.count() > 0 else ""

        return ScrapedJob(
            title=title,
            company=company,
            location=location,
            url=url,
            source=self.source_name,
            description=description,
        )
