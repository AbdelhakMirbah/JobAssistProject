"""
src/scrapers/base_scraper.py
────────────────────────────────────────────────────────────────────────────────
Strategy Pattern — Abstract Base class for all job-board scrapers.

Each concrete scraper (LinkedIn, Indeed, etc.) must implement this interface.
The main orchestration layer works exclusively against ``BaseScraper``; swapping
job boards requires only providing a new strategy class.

ISO/IEC 25010 — Maintainability: Open/Closed Principle ensures new boards are
added without modifying existing code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ScrapedJob:
    """
    Data Transfer Object returned by every scraper strategy.

    Fields map 1-to-1 to ``src.db.models.Job`` columns.
    """

    title: str
    company: str
    url: str
    source: str
    location: str = field(default="")
    description: str = field(default="")


class BaseScraper(ABC):
    """
    Abstract strategy interface that all job-board scrapers must implement.

    Subclasses must override ``scrape()`` and ``source_name``.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the board identifier string (e.g. ``"linkedin"``)."""
        ...

    @abstractmethod
    async def scrape(self, query: str, location: str, max_results: int = 25) -> list[ScrapedJob]:
        """
        Scrape job listings matching ``query`` in ``location``.

        Parameters
        ----------
        query:
            Search keywords (e.g. "Python Engineer").
        location:
            City or remote descriptor.
        max_results:
            Upper bound on results returned. Implementations should respect
            this to avoid excessive resource usage.

        Returns
        -------
        list[ScrapedJob]
            Parsed job listings. Empty list if none found or on error.
        """
        ...
