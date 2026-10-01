"""
src/db/repository.py
────────────────────────────────────────────────────────────────────────────────
Repository Pattern — abstracts all SQL operations from business logic.

Design
------
* ``JobRepository``         → CRUD for the ``jobs`` table.
* ``ApplicationRepository`` → CRUD for the ``applications`` table.

Both accept a ``Session`` injected at construction time (Dependency Injection),
making them trivially testable with an in-memory SQLite session.

ISO/IEC 25010 — Maintainability: The rest of the application never writes a
raw SQL query; schema migrations only require changes in this module.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import Application, ApplicationStatus, Job
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ── Job Repository ────────────────────────────────────────────────────────────


class JobRepository:
    """All database interactions for the ``jobs`` table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Write ──────────────────────────────────────────────────────────────

    def add(self, job: Job) -> Job:
        """
        Persist a new Job.

        Returns the persisted instance (with its auto-assigned ``id``).

        Raises
        ------
        IntegrityError
            If a Job with the same URL already exists (unique constraint).
        """
        self._session.add(job)
        self._session.flush()   # Populate job.id without committing.
        logger.debug("Added Job id=%s url=%s", job.id, job.url)
        return job

    def add_or_ignore(self, job: Job) -> Job | None:
        """
        Attempt to add a Job; return ``None`` if the URL already exists.

        This is the preferred method for scrapers to avoid duplicate rows.
        """
        try:
            result = self.add(job)
            return result
        except IntegrityError:
            self._session.rollback()
            logger.info("Duplicate job URL skipped: %s", job.url)
            return None

    def update(self, job: Job) -> Job:
        """Merge a detached or modified Job back into the session."""
        merged = self._session.merge(job)
        self._session.flush()
        logger.debug("Updated Job id=%s", merged.id)
        return merged

    def delete(self, job_id: int) -> bool:
        """
        Delete a Job by primary key.

        Returns ``True`` if a row was deleted, ``False`` if not found.
        """
        job = self.get_by_id(job_id)
        if job is None:
            logger.warning("Delete attempted on non-existent Job id=%s", job_id)
            return False
        self._session.delete(job)
        self._session.flush()
        logger.debug("Deleted Job id=%s", job_id)
        return True

    # ── Read ───────────────────────────────────────────────────────────────

    def get_by_id(self, job_id: int) -> Job | None:
        """Return the Job with the given PK, or ``None``."""
        return self._session.get(Job, job_id)

    def get_by_url(self, url: str) -> Job | None:
        """Return the Job matching the given URL, or ``None``."""
        stmt = select(Job).where(Job.url == url)
        return self._session.scalars(stmt).first()

    def list_all(self) -> Sequence[Job]:
        """Return all Jobs ordered by ``scraped_at`` descending."""
        stmt = select(Job).order_by(Job.scraped_at.desc())
        return self._session.scalars(stmt).all()

    def list_by_source(self, source: str) -> Sequence[Job]:
        """Return all Jobs from a specific board (e.g. ``"linkedin"``)."""
        stmt = select(Job).where(Job.source == source).order_by(Job.scraped_at.desc())
        return self._session.scalars(stmt).all()

    def search(self, keyword: str) -> Sequence[Job]:
        """
        Case-insensitive keyword search across ``title`` and ``description``.

        Uses SQLite ``LIKE`` — sufficient for local usage.
        """
        pattern = f"%{keyword}%"
        stmt = select(Job).where(
            Job.title.ilike(pattern) | Job.description.ilike(pattern)
        )
        return self._session.scalars(stmt).all()


# ── Application Repository ────────────────────────────────────────────────────


class ApplicationRepository:
    """All database interactions for the ``applications`` table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Write ──────────────────────────────────────────────────────────────

    def add(self, application: Application) -> Application:
        """Persist a new Application and flush to populate its PK."""
        self._session.add(application)
        self._session.flush()
        logger.debug("Added Application id=%s job_id=%s", application.id, application.job_id)
        return application

    def update_status(
        self,
        application_id: int,
        new_status: ApplicationStatus,
    ) -> Application | None:
        """
        Transition an Application to ``new_status``.

        Automatically sets ``applied_at`` when transitioning to ``APPLIED``.

        Returns the updated instance, or ``None`` if not found.
        """
        app = self.get_by_id(application_id)
        if app is None:
            logger.warning(
                "Status update on non-existent Application id=%s", application_id
            )
            return None

        prev = app.status
        app.status = new_status
        if new_status == ApplicationStatus.APPLIED and app.applied_at is None:
            app.applied_at = datetime.now(UTC)

        self._session.flush()
        logger.info(
            "Application id=%s status: %s → %s", application_id, prev.value, new_status.value
        )
        return app

    def save_documents(
        self,
        application_id: int,
        cover_letter: str | None = None,
        tailored_resume: str | None = None,
    ) -> Application | None:
        """
        Attach AI-generated documents to an existing Application.

        Returns the updated instance, or ``None`` if not found.
        """
        app = self.get_by_id(application_id)
        if app is None:
            logger.warning(
                "save_documents on non-existent Application id=%s", application_id
            )
            return None
        if cover_letter is not None:
            app.cover_letter = cover_letter
        if tailored_resume is not None:
            app.tailored_resume = tailored_resume
        self._session.flush()
        logger.debug("Documents saved for Application id=%s", application_id)
        return app

    def delete(self, application_id: int) -> bool:
        """Delete an Application by PK. Returns ``True`` if deleted."""
        app = self.get_by_id(application_id)
        if app is None:
            return False
        self._session.delete(app)
        self._session.flush()
        return True

    # ── Read ───────────────────────────────────────────────────────────────

    def get_by_id(self, application_id: int) -> Application | None:
        """Return the Application with the given PK, or ``None``."""
        return self._session.get(Application, application_id)

    def get_by_job_id(self, job_id: int) -> Application | None:
        """Return the Application linked to ``job_id``, or ``None``."""
        stmt = select(Application).where(Application.job_id == job_id)
        return self._session.scalars(stmt).first()

    def list_by_status(self, status: ApplicationStatus) -> Sequence[Application]:
        """Return all Applications in the given status."""
        stmt = (
            select(Application)
            .where(Application.status == status)
            .order_by(Application.created_at.desc())
        )
        return self._session.scalars(stmt).all()

    def list_all(self) -> Sequence[Application]:
        """Return all Applications ordered by creation date descending."""
        stmt = select(Application).order_by(Application.created_at.desc())
        return self._session.scalars(stmt).all()
