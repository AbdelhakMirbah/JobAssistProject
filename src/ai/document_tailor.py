"""
src/ai/document_tailor.py
────────────────────────────────────────────────────────────────────────────────
AI Document Tailor — wraps the Google Gemini API to produce tailored cover
letters and resume summaries.

Design
------
* ``DocumentTailor`` is the main class. Constructor accepts an optional API key
  override; otherwise reads ``GEMINI_API_KEY`` from the environment via
  python-dotenv.
* All prompts are kept in private methods so they can be independently tested
  or swapped (Strategy-compatible).
* Retry logic uses exponential back-off with jitter for transient API errors.
* The class raises ``DocumentTailorError`` (a custom exception) on unrecoverable
  failures so callers can handle AI failures distinctly from DB/IO failures.

Security: API key is NEVER logged or included in exceptions.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from typing import Final

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types

from src.utils.logger import get_logger

load_dotenv()  # Loads .env into os.environ (safe no-op if missing)

logger = get_logger(__name__)

# ── OmniRoute integration (optional — activated by USE_OMNIROUTE=true) ────────
try:
    from src.ai.omniroute_client import OmniRouteClient, OmniRouteError, get_omniroute_client
    _OMNIROUTE_AVAILABLE = True
except ImportError:
    _OMNIROUTE_AVAILABLE = False
    OmniRouteClient = None  # type: ignore[misc,assignment]
    OmniRouteError = Exception  # type: ignore[misc,assignment]
    def get_omniroute_client(): return None  # type: ignore[misc]



# ── Constants ─────────────────────────────────────────────────────────────────

_MODEL: Final[str] = "gemini-3.1-pro-preview"  # Successor to gemini-2.5-pro
_MAX_RETRIES: Final[int] = 3
_BASE_BACKOFF_S: Final[float] = 2.0   # Seconds before first retry
_MAX_BACKOFF_S: Final[float] = 30.0   # Cap on wait time


# ── Custom Exceptions ─────────────────────────────────────────────────────────


class DocumentTailorError(Exception):
    """Raised when the AI module cannot produce a result after all retries."""


# ── Data Transfer Objects ─────────────────────────────────────────────────────


@dataclass
class TailoredDocuments:
    """
    Container for the AI-generated artefacts for a single job application.

    Attributes
    ----------
    cover_letter    : Formatted cover letter text.
    resume_summary  : 3–4 bullet-point summary tailored to the job description.
    keywords        : Key skills/terms extracted from the job description.
    """

    cover_letter: str = field(default="")
    resume_summary: str = field(default="")
    keywords: list[str] = field(default_factory=list)


# ── Main Class ────────────────────────────────────────────────────────────────


class DocumentTailor:
    """
    Generates job-application documents tailored to a specific job description.

    Parameters
    ----------
    api_key:
        Gemini API key. Defaults to ``GEMINI_API_KEY`` env-var.
    model:
        Gemini model identifier. Defaults to ``gemini-2.5-pro``.
    max_retries:
        Number of retry attempts on transient API errors.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _MODEL,  # override with e.g. "gemini-1.5-pro" if needed
        max_retries: int = _MAX_RETRIES,
        omni_client: object | None = None,  # OmniRouteClient, injected or auto-detected
    ) -> None:
        # ── OmniRoute integration (USE_OMNIROUTE=true) ────────────────────
        self._omni: OmniRouteClient | None = (
            omni_client  # type: ignore[assignment]
            if omni_client is not None
            else (get_omniroute_client() if _OMNIROUTE_AVAILABLE else None)
        )
        if self._omni is not None:
            logger.info(
                "DocumentTailor using OmniRoute backend (model=auto). "
                "Gemini is the fallback."
            )

        # ── Gemini (primary or fallback) ──────────────────────────────────
        resolved_key = api_key or os.getenv("GEMINI_API_KEY")
        if not resolved_key and self._omni is None:
            raise DocumentTailorError(
                "No AI backend available. Either:\n"
                "  • Set GEMINI_API_KEY in your .env  (direct Gemini access)\n"
                "  • Set USE_OMNIROUTE=true and run: omniroute  (free gateway)"
            )
        if resolved_key:
            self._client = genai.Client(api_key=resolved_key)
        else:
            self._client = None  # type: ignore[assignment]  # OmniRoute-only mode

        self._model = model
        self._max_retries = max_retries
        logger.info(
            "DocumentTailor initialised | gemini=%s | omniroute=%s",
            self._model if resolved_key else "disabled",
            "enabled" if self._omni else "disabled",
        )

    # ── Public API ────────────────────────────────────────────────────────

    def tailor(
        self,
        job_description: str,
        master_resume: str,
        applicant_name: str = "Applicant",
        company_name: str = "the company",
        job_title: str = "the role",
    ) -> TailoredDocuments:
        """
        Produce a ``TailoredDocuments`` object for the given job.

        Parameters
        ----------
        job_description:
            Raw text of the job listing (skills, requirements, responsibilities).
        master_resume:
            Full master resume text — the AI uses this as source material.
        applicant_name:
            Used to personalise the cover letter salutation.
        company_name:
            Target employer name for the cover letter.
        job_title:
            Target job title for the cover letter.

        Returns
        -------
        TailoredDocuments
            Populated with ``cover_letter``, ``resume_summary``, and
            ``keywords``.

        Raises
        ------
        DocumentTailorError
            On unrecoverable API failure.
        """
        logger.info(
            "Tailoring documents for job_title=%r company=%r", job_title, company_name
        )

        cover_letter = self._generate_with_retry(
            self._cover_letter_prompt(
                job_description, master_resume, applicant_name, company_name, job_title
            )
        )

        resume_summary = self._generate_with_retry(
            self._resume_summary_prompt(job_description, master_resume)
        )

        keywords = self._extract_keywords(job_description)

        return TailoredDocuments(
            cover_letter=cover_letter,
            resume_summary=resume_summary,
            keywords=keywords,
        )

    def generate_cover_letter(
        self,
        job_description: str,
        master_resume: str,
        applicant_name: str = "Applicant",
        company_name: str = "the company",
        job_title: str = "the role",
    ) -> str:
        """
        Convenience method — generate only the cover letter.

        This is the primary method referenced in the project spec:
        *"takes a job description and a master resume string, and returns a
        tailored cover letter"*.

        Returns
        -------
        str
            The generated cover letter.
        """
        prompt = self._cover_letter_prompt(
            job_description, master_resume, applicant_name, company_name, job_title
        )
        return self._generate_with_retry(prompt)

    # ── Private: Prompt Builders ──────────────────────────────────────────

    @staticmethod
    def _cover_letter_prompt(
        job_description: str,
        master_resume: str,
        applicant_name: str,
        company_name: str,
        job_title: str,
    ) -> str:
        return f"""You are an expert career coach and professional writer.
Your task is to write a compelling, personalised cover letter.

## Instructions
- Address the letter to the hiring team at {company_name}.
- The applicant's name is: {applicant_name}.
- The target role is: {job_title}.
- Draw ONLY from the experience and skills in the master resume below.
- Mirror the language and key terms from the job description.
- Keep it to 3–4 concise paragraphs. Do NOT include a date or address header.
- End with a professional sign-off.

## Job Description
{job_description}

## Master Resume
{master_resume}

## Output
Write the cover letter below. Do not add any commentary or preamble.
"""

    @staticmethod
    def _resume_summary_prompt(job_description: str, master_resume: str) -> str:
        return f"""You are an expert ATS optimisation specialist.
Your task is to produce a tailored professional summary for the top of a resume.

## Instructions
- Write 3–5 bullet points highlighting the most relevant experience from the
  master resume for the given job description.
- Each bullet point should begin with a strong action verb.
- Incorporate key terms from the job description for ATS compatibility.
- Do NOT invent experience not present in the master resume.

## Job Description
{job_description}

## Master Resume
{master_resume}

## Output
Return ONLY the bullet points, each on its own line, starting with "• ".
"""

    # ── Private: API Interaction ──────────────────────────────────────────

    def _generate_with_retry(self, prompt: str) -> str:
        """
        Call the AI backend with exponential back-off retry on transient errors.

        Routing priority:
          1. OmniRoute (if USE_OMNIROUTE=true and server is running)  — free, auto-fallback
          2. Gemini (direct google-genai SDK)                         — requires API key + quota

        Parameters
        ----------
        prompt:
            The full prompt string to send.

        Returns
        -------
        str
            The model's text response.

        Raises
        ------
        DocumentTailorError
            After all retry attempts are exhausted.
        """
        # ── Path 1: OmniRoute ─────────────────────────────────────────────
        if self._omni is not None:
            try:
                text = self._omni.generate(prompt)
                if not text:
                    raise DocumentTailorError("OmniRoute returned an empty response.")
                logger.debug("OmniRoute responded successfully")
                return text.strip()
            except DocumentTailorError:
                raise
            except OmniRouteError as exc:
                logger.warning(
                    "OmniRoute failed: %s — falling back to Gemini (if available)", exc
                )
                if self._client is None:
                    raise DocumentTailorError(
                        f"OmniRoute failed and no Gemini API key is configured. "
                        f"Error: {exc}"
                    ) from exc
                # Fall through to Gemini below

        # ── Path 2: Gemini direct ─────────────────────────────────────────
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                logger.debug("Gemini API call attempt %d/%d", attempt, self._max_retries)
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=2048,
                    ),
                )
                text = response.text
                if not text:
                    raise DocumentTailorError("Gemini returned an empty response.")
                logger.debug("Gemini API call succeeded on attempt %d", attempt)
                return text.strip()

            except DocumentTailorError:
                raise  # Non-retryable: empty response is not a transient error.
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait = min(
                    _BASE_BACKOFF_S * (2 ** (attempt - 1)) + random.uniform(0, 1),
                    _MAX_BACKOFF_S,
                )
                logger.warning(
                    "Gemini API error on attempt %d/%d: %s — retrying in %.1fs",
                    attempt,
                    self._max_retries,
                    type(exc).__name__,
                    wait,
                )
                time.sleep(wait)

        raise DocumentTailorError(
            f"Gemini API failed after {self._max_retries} retries. "
            f"Last error type: {type(last_exc).__name__}"
        ) from last_exc

    def _extract_keywords(self, job_description: str) -> list[str]:
        """
        Extract top ATS keywords from the job description.

        Returns a list of keyword strings, or an empty list on failure
        (non-critical path — callers should not depend on this succeeding).
        """
        prompt = f"""Extract the 10 most important technical skills and keywords from
the following job description. Return ONLY a comma-separated list, no commentary.

Job Description:
{job_description}
"""
        try:
            raw = self._generate_with_retry(prompt)
            return [kw.strip() for kw in raw.split(",") if kw.strip()]
        except DocumentTailorError:
            logger.warning("Keyword extraction failed; returning empty list.")
            return []
