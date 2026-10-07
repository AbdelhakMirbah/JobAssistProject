"""
src/ai/omniroute_client.py
────────────────────────────────────────────────────────────────────────────────
OmniRoute AI Client — connects JobAssist to OmniRoute's local gateway.

OmniRoute (github.com/diegosouzapw/OmniRoute) is a free MIT AI gateway that
exposes a single OpenAI-compatible endpoint aggregating 359 providers, 150+
free tiers (~1.62B free tokens/month), and automatic quota-aware fallback.

This client wraps OmniRoute's /v1/chat/completions endpoint using httpx,
providing the same interface as DocumentTailor's internal call so it can be
swapped in transparently via USE_OMNIROUTE=true in .env.

How it works:
  1. OmniRoute runs locally on port 20128 (npm i -g omniroute)
  2. This client calls http://localhost:20128/v1/chat/completions
  3. Model "auto" lets OmniRoute pick the best free provider automatically
  4. No API key required for the free tier — just start OmniRoute

Design contract (ISO/IEC 25010 — Maintainability):
  - Same generate(prompt: str) → str interface as Gemini calls in document_tailor
  - Raises OmniRouteError on failure (mirrors DocumentTailorError semantics)
  - Full retry logic with exponential back-off
"""
from __future__ import annotations

import json
import os
import random
import time
from typing import Final

import httpx

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_OMNIROUTE_BASE_URL: Final[str] = "http://localhost:20128"
_OMNIROUTE_ENDPOINT: Final[str] = f"{_OMNIROUTE_BASE_URL}/v1/chat/completions"

# Default model — "auto" lets OmniRoute pick the best available free provider.
# Other good options:
#   "auto/coding"   → quality-first for code generation
#   "auto/fast"     → lowest latency
#   "auto/cheap"    → cheapest per token
#   "auto/offline"  → most quota headroom (best for heavy batch jobs)
_DEFAULT_MODEL: Final[str] = "auto"

_MAX_RETRIES: Final[int] = 3
_BASE_BACKOFF_S: Final[float] = 1.5
_MAX_BACKOFF_S: Final[float] = 20.0
_REQUEST_TIMEOUT_S: Final[float] = 120.0   # OmniRoute may queue; be generous


class OmniRouteError(Exception):
    """Raised when OmniRoute fails after all retries."""


class OmniRouteClient:
    """
    HTTP client for OmniRoute's local OpenAI-compatible gateway.

    Parameters
    ----------
    base_url:
        OmniRoute base URL (default: http://localhost:20128).
    model:
        OmniRoute model or combo to use (default: "auto").
    max_retries:
        Number of attempts before raising OmniRouteError.
    timeout:
        HTTP request timeout in seconds.

    Usage
    -----
    >>> client = OmniRouteClient()
    >>> text = client.generate("Write a cover letter for a Python engineer role.")
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        max_retries: int = _MAX_RETRIES,
        timeout: float = _REQUEST_TIMEOUT_S,
    ) -> None:
        self._base_url = (
            base_url
            or os.getenv("OMNIROUTE_URL", _OMNIROUTE_BASE_URL)
        ).rstrip("/")
        self._endpoint = f"{self._base_url}/v1/chat/completions"
        self._model = (
            model
            or os.getenv("OMNIROUTE_MODEL", _DEFAULT_MODEL)
        )
        self._max_retries = max_retries
        self._timeout = timeout

        logger.info(
            "OmniRouteClient initialised — endpoint=%s model=%s",
            self._endpoint,
            self._model,
        )

    # ── Public interface ──────────────────────────────────────────────────────

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """
        Send a prompt to OmniRoute and return the text response.

        Parameters
        ----------
        prompt:
            The user prompt text.
        system_prompt:
            Optional system message (persona/instruction context).

        Returns
        -------
        str
            The model's text response.

        Raises
        ------
        OmniRouteError
            If all retries fail.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return self._request_with_retry(messages)

    def health_check(self) -> bool:
        """
        Check if OmniRoute is running and reachable.

        Returns True if the server is up, False otherwise.
        Never raises — safe to call as a guard condition.
        """
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{self._base_url}/health")
                return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    # ── Private: HTTP + retry ─────────────────────────────────────────────────

    def _request_with_retry(self, messages: list[dict]) -> str:
        """POST to OmniRoute with exponential back-off retry."""
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.debug(
                    "OmniRoute attempt %d/%d model=%s",
                    attempt, self._max_retries, self._model,
                )
                text = self._post(payload)
                logger.debug("OmniRoute responded successfully on attempt %d", attempt)
                return text

            except OmniRouteError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    wait = min(
                        _BASE_BACKOFF_S * (2 ** (attempt - 1))
                        + random.uniform(0, 1.0),
                        _MAX_BACKOFF_S,
                    )
                    logger.warning(
                        "OmniRoute error attempt %d/%d — retrying in %.1fs: %s",
                        attempt, self._max_retries, wait, exc,
                    )
                    time.sleep(wait)

        raise OmniRouteError(
            f"OmniRoute failed after {self._max_retries} retries. "
            f"Last error: {last_exc}"
        )

    def _post(self, payload: dict) -> str:
        """Execute a single HTTP POST to OmniRoute. Raises OmniRouteError on failure."""
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    self._endpoint,
                    headers={"Content-Type": "application/json"},
                    content=json.dumps(payload),
                )
        except httpx.ConnectError as exc:
            raise OmniRouteError(
                f"Cannot connect to OmniRoute at {self._endpoint}. "
                "Is OmniRoute running? Start it with: omniroute"
            ) from exc
        except httpx.TimeoutException as exc:
            raise OmniRouteError(
                f"OmniRoute request timed out after {self._timeout}s. "
                "The model may be under high load."
            ) from exc
        except httpx.RequestError as exc:
            raise OmniRouteError(f"OmniRoute HTTP error: {type(exc).__name__}") from exc

        if response.status_code not in (200, 201):
            raise OmniRouteError(
                f"OmniRoute returned HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise OmniRouteError(
                f"Unexpected OmniRoute response format: {response.text[:200]}"
            ) from exc


def is_omniroute_enabled() -> bool:
    """
    Return True if OmniRoute integration is enabled via env var.

    Set USE_OMNIROUTE=true in your .env to activate.
    """
    return os.getenv("USE_OMNIROUTE", "").lower() in ("true", "1", "yes")


def get_omniroute_client() -> OmniRouteClient | None:
    """
    Return an OmniRouteClient if enabled and reachable, else None.

    Logs a warning if enabled but OmniRoute is not running.
    """
    if not is_omniroute_enabled():
        return None

    client = OmniRouteClient()
    if not client.health_check():
        logger.warning(
            "USE_OMNIROUTE=true but OmniRoute is not reachable at %s. "
            "Start it with: omniroute  (requires: npm i -g omniroute)",
            client._base_url,
        )
        return None

    logger.info("OmniRoute is enabled and reachable — using as AI backend")
    return client
