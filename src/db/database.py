"""
src/db/database.py
────────────────────────────────────────────────────────────────────────────────
Database engine and session factory for JobAssist.

Responsibilities
----------------
* Create the SQLAlchemy engine from ``DATABASE_URL`` env-var (falls back to a
  local SQLite file ``./jobassist.db``).
* Expose ``get_session()`` as a context manager for safe session handling.
* Run ``init_db()`` to create all tables (idempotent / CREATE IF NOT EXISTS).

Security note: the connection URL is read exclusively from the environment;
no credentials are ever embedded in source code.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Engine ────────────────────────────────────────────────────────────────────

_DEFAULT_URL = "sqlite:///./jobassist.db"


def _build_engine(database_url: str | None = None) -> Engine:
    """
    Construct and return a SQLAlchemy Engine.

    Parameters
    ----------
    database_url:
        Explicit URL override. Falls back to the ``DATABASE_URL`` env-var,
        then to the default SQLite path.
    """
    url = database_url or os.getenv("DATABASE_URL", _DEFAULT_URL)
    logger.info("Initialising database engine: %s", url)

    connect_args: dict = {}
    if url.startswith("sqlite"):
        # SQLite requires check_same_thread=False when using a single
        # in-memory/file DB across multiple threads (e.g. web server).
        connect_args["check_same_thread"] = False

    engine = create_engine(
        url,
        connect_args=connect_args,
        echo=False,          # Set True for SQL query logging during debugging
        pool_pre_ping=True,  # Reliability: discard stale connections
    )

    # Enable WAL mode for SQLite → better concurrency & reliability.
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_wal_mode(dbapi_conn, _connection_record):  # noqa: ANN001
            dbapi_conn.execute("PRAGMA journal_mode=WAL;")
            dbapi_conn.execute("PRAGMA foreign_keys=ON;")

    return engine


# Module-level singletons (lazy-initialised via init_db / get_session).
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def init_db(database_url: str | None = None) -> Engine:
    """
    Initialise the engine, create all tables, and return the engine.

    Safe to call multiple times — ``create_all`` is idempotent.
    """
    global _engine, _SessionLocal
    _engine = _build_engine(database_url)
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=_engine)
    logger.info("Database schema initialised successfully.")
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Yield a SQLAlchemy Session, committing on success and rolling back on error.

    Usage
    -----
    >>> with get_session() as session:
    ...     session.add(some_object)

    Raises
    ------
    RuntimeError
        If ``init_db()`` has not been called before the first ``get_session()``
        call.
    """
    if _SessionLocal is None:
        raise RuntimeError(
            "Database not initialised. Call `init_db()` before using `get_session()`."
        )

    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Session rolled back due to an unhandled exception.")
        raise
    finally:
        session.close()
