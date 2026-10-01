"""
tests/test_ai.py
────────────────────────────────────────────────────────────────────────────────
Unit tests for src.ai.document_tailor.

Strategy
--------
* The Gemini API is ALWAYS mocked — tests never make live network calls.
* We test the public contract, prompt-building logic, retry behaviour, and
  error propagation independently.
* pytest-mock's ``mocker`` fixture patches ``google.genai.Client`` at the
  point of use (``src.ai.document_tailor``).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ai.document_tailor import DocumentTailor, DocumentTailorError, TailoredDocuments

# ── Test constants ────────────────────────────────────────────────────────────

_FAKE_KEY = "test-api-key-not-real"
_JD = "We need a Senior Python Engineer with Django, FastAPI, and AWS experience."
_RESUME = "Jane Doe. 6 years Python. Built Django REST APIs at scale. AWS Certified."


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_tailor(mock_client: MagicMock) -> DocumentTailor:
    """Instantiate DocumentTailor with a patched genai.Client."""
    with patch("src.ai.document_tailor.genai.Client", return_value=mock_client):
        return DocumentTailor(api_key=_FAKE_KEY, max_retries=2)


def _mock_response(text: str) -> MagicMock:
    """Return a mock object that looks like a Gemini GenerateContentResponse."""
    resp = MagicMock()
    resp.text = text
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# Initialisation
# ═══════════════════════════════════════════════════════════════════════════════


class TestDocumentTailorInit:
    """Tests for constructor validation."""

    def test_raises_if_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing GEMINI_API_KEY must raise DocumentTailorError."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(DocumentTailorError, match="GEMINI_API_KEY"):
            DocumentTailor(api_key=None)

    def test_accepts_explicit_api_key(self) -> None:
        """An explicit key bypasses the env-var requirement."""
        with patch("src.ai.document_tailor.genai.Client"):
            tailor = DocumentTailor(api_key=_FAKE_KEY)
        assert tailor is not None

    def test_accepts_env_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GEMINI_API_KEY from env is accepted without explicit key."""
        monkeypatch.setenv("GEMINI_API_KEY", _FAKE_KEY)
        with patch("src.ai.document_tailor.genai.Client"):
            tailor = DocumentTailor()
        assert tailor is not None


# ═══════════════════════════════════════════════════════════════════════════════
# generate_cover_letter
# ═══════════════════════════════════════════════════════════════════════════════


class TestGenerateCoverLetter:
    """Tests for the primary generate_cover_letter method."""

    def test_returns_string_on_success(self) -> None:
        """Successful API call returns a non-empty string."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(
            "Dear Hiring Team, I am excited to apply…"
        )
        tailor = _make_tailor(mock_client)

        result = tailor.generate_cover_letter(
            job_description=_JD,
            master_resume=_RESUME,
            applicant_name="Jane Doe",
            company_name="Acme Corp",
            job_title="Senior Python Engineer",
        )

        assert isinstance(result, str)
        assert len(result) > 0

    def test_strips_whitespace_from_response(self) -> None:
        """Leading/trailing whitespace is stripped from the returned text."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(
            "  \n  Cover letter body.  \n  "
        )
        tailor = _make_tailor(mock_client)

        result = tailor.generate_cover_letter(_JD, _RESUME)
        assert result == "Cover letter body."

    def test_api_called_with_correct_model(self) -> None:
        """The API is called with the configured model identifier."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response("Letter text")
        tailor = _make_tailor(mock_client)

        tailor.generate_cover_letter(_JD, _RESUME)

        call_kwargs = mock_client.models.generate_content.call_args
        assert call_kwargs.kwargs["model"] == "gemini-2.5-pro"

    def test_raises_on_empty_response(self) -> None:
        """An empty API response raises DocumentTailorError immediately."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response("")
        tailor = _make_tailor(mock_client)

        with pytest.raises(DocumentTailorError, match="empty response"):
            tailor.generate_cover_letter(_JD, _RESUME)

    def test_prompt_contains_job_description(self) -> None:
        """The prompt sent to the API includes the job description text."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response("Letter")
        tailor = _make_tailor(mock_client)

        tailor.generate_cover_letter(_JD, _RESUME)

        prompt_arg = mock_client.models.generate_content.call_args.kwargs["contents"]
        assert _JD in prompt_arg

    def test_prompt_contains_master_resume(self) -> None:
        """The prompt sent to the API includes the master resume text."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response("Letter")
        tailor = _make_tailor(mock_client)

        tailor.generate_cover_letter(_JD, _RESUME)

        prompt_arg = mock_client.models.generate_content.call_args.kwargs["contents"]
        assert _RESUME in prompt_arg


# ═══════════════════════════════════════════════════════════════════════════════
# Retry Logic
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryBehaviour:
    """Tests that the exponential back-off retry mechanism works correctly."""

    def test_retries_on_transient_error(self) -> None:
        """
        The client retries on generic exceptions and succeeds on the second
        attempt.
        """
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            RuntimeError("Transient network error"),
            _mock_response("Success on retry"),
        ]

        with (
            patch("src.ai.document_tailor.genai.Client", return_value=mock_client),
            patch("src.ai.document_tailor.time.sleep"),  # Skip real sleep in tests
        ):
            tailor = DocumentTailor(api_key=_FAKE_KEY, max_retries=2)
            result = tailor.generate_cover_letter(_JD, _RESUME)

        assert result == "Success on retry"
        assert mock_client.models.generate_content.call_count == 2

    def test_raises_after_all_retries_exhausted(self) -> None:
        """DocumentTailorError is raised when all retries are exhausted."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("Always fails")

        with (
            patch("src.ai.document_tailor.genai.Client", return_value=mock_client),
            patch("src.ai.document_tailor.time.sleep"),
        ):
            tailor = DocumentTailor(api_key=_FAKE_KEY, max_retries=3)
            with pytest.raises(DocumentTailorError, match="3 retries"):
                tailor.generate_cover_letter(_JD, _RESUME)

        assert mock_client.models.generate_content.call_count == 3

    def test_sleep_called_between_retries(self) -> None:
        """``time.sleep`` is invoked between retry attempts."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            RuntimeError("Fail 1"),
            RuntimeError("Fail 2"),
            _mock_response("OK"),
        ]

        with (
            patch("src.ai.document_tailor.genai.Client", return_value=mock_client),
            patch("src.ai.document_tailor.time.sleep") as mock_sleep,
        ):
            tailor = DocumentTailor(api_key=_FAKE_KEY, max_retries=3)
            tailor.generate_cover_letter(_JD, _RESUME)

        # sleep should have been called once per failed attempt (2 failures)
        assert mock_sleep.call_count == 2


# ═══════════════════════════════════════════════════════════════════════════════
# tailor() — full document generation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTailorMethod:
    """Tests for the composite tailor() method."""

    def test_returns_tailored_documents_instance(self) -> None:
        """``tailor()`` returns a ``TailoredDocuments`` dataclass."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(
            "Some text, Python, Django, FastAPI"
        )
        tailor = _make_tailor(mock_client)

        result = tailor.tailor(_JD, _RESUME)
        assert isinstance(result, TailoredDocuments)

    def test_cover_letter_field_populated(self) -> None:
        """The ``cover_letter`` field of ``TailoredDocuments`` is non-empty."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(
            "Cover letter, Python, Django"
        )
        tailor = _make_tailor(mock_client)

        result = tailor.tailor(_JD, _RESUME)
        assert result.cover_letter != ""

    def test_keywords_are_list(self) -> None:
        """The ``keywords`` field is always a list, even on partial failure."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(
            "Python, Django, FastAPI, AWS"
        )
        tailor = _make_tailor(mock_client)

        result = tailor.tailor(_JD, _RESUME)
        assert isinstance(result.keywords, list)

    def test_keywords_extracted_from_comma_list(self) -> None:
        """Keywords are correctly split from a comma-separated response."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_response(
            "Python, Django, FastAPI, AWS, PostgreSQL"
        )
        tailor = _make_tailor(mock_client)

        result = tailor.tailor(_JD, _RESUME)
        assert "Python" in result.keywords
        assert "Django" in result.keywords
