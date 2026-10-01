"""
src/utils/logger.py
────────────────────────────────────────────────────────────────────────────────
Centralised logging factory for JobAssist.

All modules obtain a child logger via `get_logger(__name__)` so that the root
logger can be configured in one place (e.g. in main.py or tests/conftest.py).

ISO/IEC 25010 — Reliability: structured, levelled logging enables post-mortem
diagnosis and production monitoring.
"""
from __future__ import annotations

import logging
import os
import sys


def configure_root_logger(level: str | None = None) -> None:
    """
    Configure the root logger once at application startup.

    Parameters
    ----------
    level:
        Override log level string (DEBUG/INFO/WARNING/ERROR/CRITICAL).
        Falls back to the ``LOG_LEVEL`` env-var, then defaults to ``INFO``.
    """
    resolved = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric = getattr(logging, resolved, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(numeric)
    # Avoid duplicate handlers on repeated calls (e.g. in tests).
    if not root.handlers:
        root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named child logger.

    Parameters
    ----------
    name:
        Typically ``__name__`` of the calling module.
    """
    return logging.getLogger(name)
