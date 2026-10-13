"""
src/scrapers/scraper_engine.py
────────────────────────────────────────────────────────────────────────────────
Scraper Engine — orchestrates multiple BaseScraper strategies, deduplicates
results, persists them to the DB via the Repository pattern, and returns the
newly added jobs.

Usage
-----
>>> engine = ScraperEngine(scrapers=[IndeedScraper(), LinkedInScraper()])
>>> jobs = await engine.run(query="Python Engineer", location="Paris", max_per_source=20)
"""
from __future__ import annotations

import asyncio

from src.db.database import get_session
from src.db.models import Job
from src.db.repository import JobRepository
from src.scrapers.base_scraper import BaseScraper, ScrapedJob
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ScraperEngine:
    """
    Orchestrates one or more scraper strategies.

    Runs all strategies concurrently, deduplicates by URL, and persists
    results to the database using add_or_ignore (safe for reruns).

    Parameters
    ----------
    scrapers:
        List of BaseScraper implementations to run.
    """

    def __init__(self, scrapers: list[BaseScraper]) -> None:
        self._scrapers = scrapers

    async def run(
        self,
        query: str,
        location: str,
        max_per_source: int = 25,
    ) -> list[Job]:
        """
        Execute all scrapers concurrently and persist new jobs to the DB.

        Parameters
        ----------
        query:
            Search keywords (e.g. "Développeur Python Senior").
        location:
            City or region (e.g. "Paris", "Lyon", "Remote France").
        max_per_source:
            Max results requested from each scraper.

        Returns
        -------
        list[Job]
            All newly inserted Job records (excludes pre-existing duplicates).
        """
        logger.info(
            "ScraperEngine starting: %d sources | query=%r | location=%r",
            len(self._scrapers),
            query,
            location,
        )

        # Run all scrapers concurrently
        tasks = [
            scraper.scrape(query, location, max_per_source)
            for scraper in self._scrapers
        ]
        results: list[list[ScrapedJob]] = await asyncio.gather(*tasks, return_exceptions=False)

        # Flatten and deduplicate by URL (in-memory, before DB insert)
        seen_urls: set[str] = set()
        all_scraped: list[ScrapedJob] = []
        for batch in results:
            for item in batch:
                if item.url not in seen_urls:
                    seen_urls.add(item.url)
                    all_scraped.append(item)

        logger.info(
            "ScraperEngine: %d unique jobs collected across all sources", len(all_scraped)
        )

        # Persist to DB
        new_jobs = self._persist(all_scraped)
        logger.info("ScraperEngine: %d new jobs added to database", len(new_jobs))
        return new_jobs

    @staticmethod
    def _persist(scraped: list[ScrapedJob]) -> list[Job]:
        """Save scraped jobs to the DB; return only newly inserted rows."""
        new_jobs: list[Job] = []
        with get_session() as session:
            repo = JobRepository(session)
            for s in scraped:
                job = Job(
                    title=s.title,
                    company=s.company,
                    location=s.location,
                    url=s.url,
                    source=s.source,
                    description=s.description,
                )
                saved = repo.add_or_ignore(job)
                if saved:
                    new_jobs.append(saved)
        return new_jobs
