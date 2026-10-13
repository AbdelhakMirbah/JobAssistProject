"""
tests/test_db.py
────────────────────────────────────────────────────────────────────────────────
Unit tests for:
  - src.db.models   (ORM model constraints and relationships)
  - src.db.repository (JobRepository & ApplicationRepository)

All tests run against an in-memory SQLite database (see conftest.py).
No external I/O. No network calls.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from src.db.models import Application, ApplicationStatus, Job
from src.db.repository import ApplicationRepository, JobRepository


# ═══════════════════════════════════════════════════════════════════════════════
# JobRepository
# ═══════════════════════════════════════════════════════════════════════════════


class TestJobRepository:
    """Tests for JobRepository CRUD and query operations."""

    def test_add_and_get_by_id(self, db_session: Session, sample_job: Job) -> None:
        """A persisted job can be retrieved by its primary key."""
        repo = JobRepository(db_session)
        added = repo.add(sample_job)
        db_session.commit()

        fetched = repo.get_by_id(added.id)
        assert fetched is not None
        assert fetched.title == "Senior Python Engineer"
        assert fetched.company == "Acme Corp"

    def test_add_assigns_primary_key(self, db_session: Session, sample_job: Job) -> None:
        """``add()`` flushes and populates the PK without committing."""
        repo = JobRepository(db_session)
        repo.add(sample_job)
        assert sample_job.id is not None
        assert sample_job.id > 0

    def test_get_by_id_returns_none_for_missing(self, db_session: Session) -> None:
        """Querying a non-existent PK returns None."""
        repo = JobRepository(db_session)
        assert repo.get_by_id(9999) is None

    def test_get_by_url(self, db_session: Session, sample_job: Job) -> None:
        """Jobs can be looked up by their URL."""
        repo = JobRepository(db_session)
        repo.add(sample_job)
        db_session.commit()

        found = repo.get_by_url("https://example.com/jobs/1")
        assert found is not None
        assert found.id == sample_job.id

    def test_get_by_url_returns_none_for_missing(self, db_session: Session) -> None:
        """Querying an unknown URL returns None."""
        repo = JobRepository(db_session)
        assert repo.get_by_url("https://no-such-url.com") is None

    def test_add_or_ignore_deduplicates(self, db_session: Session, sample_job: Job) -> None:
        """Inserting a duplicate URL silently returns None."""
        repo = JobRepository(db_session)
        first = repo.add_or_ignore(sample_job)
        db_session.commit()

        duplicate = Job(
            title="Different Title",
            company="Other Corp",
            url="https://example.com/jobs/1",  # Same URL!
            source="indeed",
        )
        second = repo.add_or_ignore(duplicate)

        assert first is not None
        assert second is None  # Duplicate was silently ignored.

    def test_list_all_returns_all_jobs(self, db_session: Session) -> None:
        """``list_all()`` returns every row."""
        repo = JobRepository(db_session)
        for i in range(3):
            repo.add(Job(
                title=f"Job {i}",
                company="Corp",
                url=f"https://example.com/jobs/{i}",
                source="linkedin",
            ))
        db_session.commit()

        all_jobs = repo.list_all()
        assert len(all_jobs) == 3

    def test_list_by_source(self, db_session: Session) -> None:
        """``list_by_source()`` filters correctly."""
        repo = JobRepository(db_session)
        repo.add(Job(title="LI Job", company="A", url="https://li.com/1", source="linkedin"))
        repo.add(Job(title="IN Job", company="B", url="https://in.com/1", source="indeed"))
        db_session.commit()

        li_jobs = repo.list_by_source("linkedin")
        assert len(li_jobs) == 1
        assert li_jobs[0].title == "LI Job"

    def test_search_by_keyword(self, db_session: Session) -> None:
        """``search()`` matches on title and description case-insensitively."""
        repo = JobRepository(db_session)
        repo.add(Job(
            title="Python Developer",
            company="A",
            url="https://example.com/j/1",
            source="linkedin",
            description="Looking for a django expert",
        ))
        repo.add(Job(
            title="Java Engineer",
            company="B",
            url="https://example.com/j/2",
            source="linkedin",
            description="Spring Boot developer needed",
        ))
        db_session.commit()

        results = repo.search("django")
        assert len(results) == 1
        assert "Python" in results[0].title

    def test_delete_existing_job(self, db_session: Session, sample_job: Job) -> None:
        """Deleting an existing job returns True and removes it."""
        repo = JobRepository(db_session)
        repo.add(sample_job)
        db_session.commit()

        deleted = repo.delete(sample_job.id)
        db_session.commit()

        assert deleted is True
        assert repo.get_by_id(sample_job.id) is None

    def test_delete_nonexistent_job_returns_false(self, db_session: Session) -> None:
        """Deleting a non-existent job returns False without error."""
        repo = JobRepository(db_session)
        assert repo.delete(99999) is False

    def test_update_job(self, db_session: Session, sample_job: Job) -> None:
        """``update()`` persists field changes."""
        repo = JobRepository(db_session)
        repo.add(sample_job)
        db_session.commit()

        sample_job.title = "Staff Python Engineer"
        repo.update(sample_job)
        db_session.commit()

        fetched = repo.get_by_id(sample_job.id)
        assert fetched.title == "Staff Python Engineer"


# ═══════════════════════════════════════════════════════════════════════════════
# ApplicationRepository
# ═══════════════════════════════════════════════════════════════════════════════


class TestApplicationRepository:
    """Tests for ApplicationRepository CRUD and status transitions."""

    def _add_job(self, db_session: Session, url: str = "https://example.com/j/1") -> Job:
        """Helper: persist a Job and return it."""
        job_repo = JobRepository(db_session)
        job = job_repo.add(Job(
            title="Test Job", company="Test Corp", url=url, source="linkedin"
        ))
        db_session.commit()
        return job

    def test_add_application(self, db_session: Session) -> None:
        """An Application can be persisted and retrieved by PK."""
        job = self._add_job(db_session)
        app_repo = ApplicationRepository(db_session)

        app = Application(job_id=job.id, status=ApplicationStatus.PENDING)
        added = app_repo.add(app)
        db_session.commit()

        fetched = app_repo.get_by_id(added.id)
        assert fetched is not None
        assert fetched.status == ApplicationStatus.PENDING

    def test_update_status_pending_to_applied(self, db_session: Session) -> None:
        """Status transition to APPLIED sets ``applied_at``."""
        job = self._add_job(db_session)
        app_repo = ApplicationRepository(db_session)
        app = app_repo.add(Application(job_id=job.id, status=ApplicationStatus.PENDING))
        db_session.commit()

        updated = app_repo.update_status(app.id, ApplicationStatus.APPLIED)
        db_session.commit()

        assert updated is not None
        assert updated.status == ApplicationStatus.APPLIED
        assert updated.applied_at is not None

    def test_update_status_nonexistent_returns_none(self, db_session: Session) -> None:
        """Updating status of a non-existent application returns None."""
        app_repo = ApplicationRepository(db_session)
        result = app_repo.update_status(99999, ApplicationStatus.REJECTED)
        assert result is None

    def test_save_documents(self, db_session: Session) -> None:
        """Cover letter and resume text are persisted correctly."""
        job = self._add_job(db_session)
        app_repo = ApplicationRepository(db_session)
        app = app_repo.add(Application(job_id=job.id))
        db_session.commit()

        app_repo.save_documents(
            app.id,
            cover_letter="Dear Hiring Team…",
            tailored_resume="• 5 years Python…",
        )
        db_session.commit()

        fetched = app_repo.get_by_id(app.id)
        assert fetched.cover_letter == "Dear Hiring Team…"
        assert fetched.tailored_resume == "• 5 years Python…"

    def test_list_by_status(self, db_session: Session) -> None:
        """``list_by_status()`` returns only matching applications."""
        job = self._add_job(db_session)
        app_repo = ApplicationRepository(db_session)
        app_repo.add(Application(job_id=job.id, status=ApplicationStatus.PENDING))

        job2 = self._add_job(db_session, url="https://example.com/j/2")
        app_repo.add(Application(job_id=job2.id, status=ApplicationStatus.APPLIED))
        db_session.commit()

        pending = app_repo.list_by_status(ApplicationStatus.PENDING)
        applied = app_repo.list_by_status(ApplicationStatus.APPLIED)

        assert len(pending) == 1
        assert len(applied) == 1

    def test_get_by_job_id(self, db_session: Session) -> None:
        """Applications can be retrieved by their linked job's PK."""
        job = self._add_job(db_session)
        app_repo = ApplicationRepository(db_session)
        added = app_repo.add(Application(job_id=job.id))
        db_session.commit()

        found = app_repo.get_by_job_id(job.id)
        assert found is not None
        assert found.id == added.id

    def test_delete_application(self, db_session: Session) -> None:
        """Deleting an application returns True and removes it."""
        job = self._add_job(db_session)
        app_repo = ApplicationRepository(db_session)
        app = app_repo.add(Application(job_id=job.id))
        db_session.commit()

        deleted = app_repo.delete(app.id)
        db_session.commit()

        assert deleted is True
        assert app_repo.get_by_id(app.id) is None

    def test_cascade_delete_on_job(self, db_session: Session) -> None:
        """Deleting a Job cascade-deletes its Applications."""
        job = self._add_job(db_session)
        app_repo = ApplicationRepository(db_session)
        app = app_repo.add(Application(job_id=job.id))
        db_session.commit()

        app_id = app.id
        job_repo = JobRepository(db_session)
        job_repo.delete(job.id)
        db_session.commit()

        assert app_repo.get_by_id(app_id) is None
