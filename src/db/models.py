"""
src/db/models.py
────────────────────────────────────────────────────────────────────────────────
SQLAlchemy ORM models for JobAssist.

Tables
------
jobs         — A scraped or manually entered job listing.
applications — One application attempt per job.

Design notes
------------
* Uses SQLAlchemy 2.x ``DeclarativeBase`` + ``Mapped`` / ``mapped_column``
  typing annotations (PEP 681 style) for full mypy / IDE coverage.
* ``__table_args__`` constraints enforce data integrity at DB level.
* Timestamps are stored in UTC (``datetime.UTC``).
"""
from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ── Base ─────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ── Enumerations ─────────────────────────────────────────────────────────────


class ApplicationStatus(str, enum.Enum):
    """Lifecycle states for a job application."""

    PENDING = "pending"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


# ── Models ────────────────────────────────────────────────────────────────────


class Job(Base):
    """
    Represents a single job listing scraped from a job board.

    Columns
    -------
    id            PK, auto-increment.
    title         Job title (e.g. "Senior Python Engineer").
    company       Employer name.
    location      City/remote descriptor.
    url           Canonical URL of the posting (unique per board).
    source        Board identifier (e.g. "linkedin", "indeed").
    description   Full job description text.
    scraped_at    UTC timestamp when the record was inserted.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("url", name="uq_jobs_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(256), nullable=False)
    location: Mapped[str] = mapped_column(String(256), nullable=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # One Job → many Applications
    applications: Mapped[list[Application]] = relationship(
        "Application", back_populates="job", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Job id={self.id} title={self.title!r} company={self.company!r}>"


class Application(Base):
    """
    Tracks the state of a job application.

    Columns
    -------
    id              PK, auto-increment.
    job_id          FK → jobs.id.
    status          Current lifecycle state (ApplicationStatus enum).
    cover_letter    AI-generated cover letter text.
    tailored_resume Path or text of the tailored resume document.
    applied_at      UTC timestamp of first APPLIED transition (nullable).
    notes           Free-form notes field.
    created_at      UTC creation timestamp.
    updated_at      UTC last-update timestamp.
    """

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, native_enum=False),
        default=ApplicationStatus.PENDING,
        nullable=False,
    )
    cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    tailored_resume: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Many Applications → one Job
    job: Mapped[Job] = relationship("Job", back_populates="applications")

    def __repr__(self) -> str:
        return (
            f"<Application id={self.id} job_id={self.job_id} status={self.status.value!r}>"
        )
