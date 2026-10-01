"""
tests/conftest.py
────────────────────────────────────────────────────────────────────────────────
Shared pytest fixtures for JobAssist.

Fixtures
--------
db_session   — In-memory SQLite session (isolated per test).
sample_job   — A pre-built Job instance (not yet persisted).
sample_app   — A pre-built Application instance (not yet persisted).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Application, ApplicationStatus, Base, Job


@pytest.fixture(scope="function")
def db_session() -> Session:
    """
    Yield a fresh, in-memory SQLite session for each test.

    The session is rolled back and the engine disposed after each test to
    guarantee full isolation.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def sample_job() -> Job:
    """Return an unsaved Job instance with realistic data."""
    return Job(
        title="Senior Python Engineer",
        company="Acme Corp",
        location="London, UK",
        url="https://example.com/jobs/1",
        source="linkedin",
        description="We need a Python expert with 5+ years experience...",
    )


@pytest.fixture
def sample_app(sample_job: Job) -> Application:
    """Return an unsaved Application linked to ``sample_job``."""
    return Application(
        job=sample_job,
        status=ApplicationStatus.PENDING,
        notes="Applied via LinkedIn Easy Apply",
    )
