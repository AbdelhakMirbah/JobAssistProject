"""
src/ai/job_analyzer.py
────────────────────────────────────────────────────────────────────────────────
AI-powered Job Analyser — uses Gemini to:

  1. Score how well a job offer matches a CV (0–100).
  2. Extract structured requirements (skills, experience, languages).
  3. Find or infer the HR contact email from the job listing.
  4. Generate personalised application tips (best strategies for this offer).
  5. Rank a list of jobs by CV match score for prioritisation.

All analysis is returned as typed dataclasses for clean downstream usage.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from src.ai.document_tailor import DocumentTailor, DocumentTailorError, _MODEL
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ── Data Transfer Objects ─────────────────────────────────────────────────────


@dataclass
class JobRequirements:
    """Structured requirements extracted from a job description."""
    required_skills: list[str] = field(default_factory=list)
    nice_to_have_skills: list[str] = field(default_factory=list)
    years_experience: str = field(default="Not specified")
    education_level: str = field(default="Not specified")
    languages: list[str] = field(default_factory=list)
    contract_type: str = field(default="Not specified")
    salary_range: str = field(default="Not specified")
    remote_policy: str = field(default="Not specified")


@dataclass
class ApplicationTip:
    """A single actionable application tip."""
    priority: int          # 1 = highest priority
    category: str          # e.g. "Cover Letter", "Keywords", "Network"
    tip: str               # The actual advice
    reason: str            # Why this tip matters for this specific job


@dataclass
class JobAnalysis:
    """
    Complete AI analysis of a job offer against a candidate's CV.

    Attributes
    ----------
    match_score     : 0–100 compatibility score.
    match_summary   : 2-3 sentence explanation of the score.
    requirements    : Structured requirements from the JD.
    matching_skills : Skills in the CV that match the JD.
    missing_skills  : Skills required by the JD but absent from the CV.
    hr_email        : Best-guess HR email (or empty string if not found).
    hr_email_source : How the email was obtained ('extracted', 'inferred', 'not_found').
    tips            : Ranked list of application tips.
    """
    match_score: int = 0
    match_summary: str = ""
    requirements: JobRequirements = field(default_factory=JobRequirements)
    matching_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    hr_email: str = ""
    hr_email_source: str = "not_found"
    tips: list[ApplicationTip] = field(default_factory=list)


# ── Main Class ────────────────────────────────────────────────────────────────


class JobAnalyzer:
    """
    AI-powered job offer analyser.

    Parameters
    ----------
    tailor:
        Injected DocumentTailor instance (reuses the same Gemini client).
        If None, creates a new one from env vars.
    """

    def __init__(self, tailor: DocumentTailor | None = None) -> None:
        self._tailor = tailor or DocumentTailor()

    def analyse(self, job_description: str, master_resume: str, company_name: str = "") -> JobAnalysis:
        """
        Run a full AI analysis of a job offer against a candidate's resume.

        Parameters
        ----------
        job_description:
            Full text of the job listing.
        master_resume:
            Candidate's full resume text.
        company_name:
            Employer name (used for email inference).

        Returns
        -------
        JobAnalysis
            Populated analysis result.
        """
        logger.info("Analysing job offer for company=%r", company_name)

        analysis = JobAnalysis()

        # --- Step 1: Match score + summary ----------------------------------
        try:
            score_data = self._get_match_score(job_description, master_resume)
            analysis.match_score = score_data.get("score", 0)
            analysis.match_summary = score_data.get("summary", "")
            analysis.matching_skills = score_data.get("matching_skills", [])
            analysis.missing_skills = score_data.get("missing_skills", [])
        except DocumentTailorError as exc:
            logger.warning("Match scoring failed: %s", exc)

        # --- Step 2: Extract structured requirements ------------------------
        try:
            analysis.requirements = self._extract_requirements(job_description)
        except DocumentTailorError as exc:
            logger.warning("Requirements extraction failed: %s", exc)

        # --- Step 3: Find HR email ------------------------------------------
        try:
            email, source = self._find_hr_email(job_description, company_name)
            analysis.hr_email = email
            analysis.hr_email_source = source
        except DocumentTailorError as exc:
            logger.warning("HR email lookup failed: %s", exc)

        # --- Step 4: Application tips ---------------------------------------
        try:
            analysis.tips = self._generate_tips(
                job_description, master_resume, analysis.missing_skills
            )
        except DocumentTailorError as exc:
            logger.warning("Tip generation failed: %s", exc)

        logger.info(
            "Analysis complete: score=%d hr_email=%r tips=%d",
            analysis.match_score,
            analysis.hr_email,
            len(analysis.tips),
        )
        return analysis

    def rank_jobs(
        self,
        jobs: list[tuple[str, str]],   # list of (job_description, job_title)
        master_resume: str,
    ) -> list[tuple[int, int, str]]:   # list of (score, index, title)
        """
        Score and rank a list of jobs by CV match, highest first.

        Parameters
        ----------
        jobs:
            List of (job_description, job_title) tuples.
        master_resume:
            Candidate resume text.

        Returns
        -------
        list of (score, original_index, job_title) sorted by score DESC.
        """
        logger.info("Ranking %d jobs by CV match", len(jobs))
        scored: list[tuple[int, int, str]] = []

        for idx, (description, title) in enumerate(jobs):
            try:
                data = self._get_match_score(description, master_resume)
                score = data.get("score", 0)
                scored.append((score, idx, title))
                logger.debug("Job[%d] %r → score %d", idx, title, score)
            except DocumentTailorError:
                scored.append((0, idx, title))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    # ── Private: AI calls ─────────────────────────────────────────────────────

    def _get_match_score(self, job_description: str, master_resume: str) -> dict:
        """Call Gemini to score CV–job compatibility. Returns parsed JSON dict."""
        prompt = f"""You are an expert ATS and recruiter AI.

Analyse the compatibility between the candidate's resume and the job description.

Return ONLY valid JSON (no markdown, no commentary) in this exact schema:
{{
  "score": <integer 0-100>,
  "summary": "<2-3 sentence explanation of the score>",
  "matching_skills": ["<skill1>", "<skill2>", ...],
  "missing_skills": ["<skill1>", "<skill2>", ...]
}}

## Job Description
{job_description}

## Candidate Resume
{master_resume}
"""
        raw = self._tailor._generate_with_retry(prompt)
        return self._parse_json(raw, default={})

    def _extract_requirements(self, job_description: str) -> JobRequirements:
        """Call Gemini to extract structured requirements. Returns JobRequirements."""
        prompt = f"""Extract structured requirements from this job description.

Return ONLY valid JSON in this exact schema (no markdown):
{{
  "required_skills": ["skill1", "skill2"],
  "nice_to_have_skills": ["skill1"],
  "years_experience": "5+ years",
  "education_level": "Bac+5 / Master",
  "languages": ["French", "English"],
  "contract_type": "CDI / Full-time",
  "salary_range": "45-60k€",
  "remote_policy": "Hybrid / 2 days remote"
}}

## Job Description
{job_description}
"""
        raw = self._tailor._generate_with_retry(prompt)
        data = self._parse_json(raw, default={})
        return JobRequirements(
            required_skills=data.get("required_skills", []),
            nice_to_have_skills=data.get("nice_to_have_skills", []),
            years_experience=data.get("years_experience", "Not specified"),
            education_level=data.get("education_level", "Not specified"),
            languages=data.get("languages", []),
            contract_type=data.get("contract_type", "Not specified"),
            salary_range=data.get("salary_range", "Not specified"),
            remote_policy=data.get("remote_policy", "Not specified"),
        )

    def _find_hr_email(self, job_description: str, company_name: str) -> tuple[str, str]:
        """
        Try to find HR email from the job description text.
        Falls back to AI inference of likely email patterns.

        Returns (email, source) where source is 'extracted' | 'inferred' | 'not_found'.
        """
        # First: try regex extraction from job description text
        emails = re.findall(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
            job_description,
        )
        # Filter out generic example emails
        real_emails = [e for e in emails if "example" not in e and "your" not in e.lower()]
        if real_emails:
            logger.info("HR email extracted from JD: %s", real_emails[0])
            return real_emails[0], "extracted"

        # Fallback: AI inference
        if not company_name:
            return "", "not_found"

        prompt = f"""A candidate wants to email their application to {company_name}.

Based on common corporate email conventions, suggest the MOST LIKELY HR/Recruitment
email address for this company.

Return ONLY valid JSON:
{{
  "email": "<best_guess_email_or_empty_string>",
  "alternatives": ["<email2>", "<email3>"],
  "confidence": "<high|medium|low>",
  "reasoning": "<one sentence explaining the pattern>"
}}

If you cannot make a reasonable inference, return an empty string for "email".
"""
        try:
            raw = self._tailor._generate_with_retry(prompt)
            data = self._parse_json(raw, default={})
            email = data.get("email", "")
            if email and "@" in email:
                logger.info("HR email inferred by AI: %s", email)
                return email, "inferred"
        except DocumentTailorError:
            pass

        return "", "not_found"

    def _generate_tips(
        self,
        job_description: str,
        master_resume: str,
        missing_skills: list[str],
    ) -> list[ApplicationTip]:
        """Generate ranked, personalised application tips using Gemini."""
        missing_str = ", ".join(missing_skills[:5]) if missing_skills else "none identified"

        prompt = f"""You are a professional career coach helping a candidate apply for this job.

Generate exactly 6 highly specific, actionable tips for this application.
Consider the candidate's CV gaps (missing skills: {missing_str}).

Return ONLY valid JSON — an array of 6 objects:
[
  {{
    "priority": 1,
    "category": "Cover Letter",
    "tip": "<specific actionable tip>",
    "reason": "<why this matters for this specific job>"
  }},
  ...
]

Categories to use (one each): Cover Letter, Keywords/ATS, Skills Gap,
Network, Follow-Up, Application Timing

## Job Description
{job_description}

## Candidate Resume
{master_resume}
"""
        raw = self._tailor._generate_with_retry(prompt)
        data = self._parse_json(raw, default=[])

        if not isinstance(data, list):
            return []

        tips = []
        for item in data:
            if isinstance(item, dict):
                tips.append(ApplicationTip(
                    priority=int(item.get("priority", 99)),
                    category=item.get("category", "General"),
                    tip=item.get("tip", ""),
                    reason=item.get("reason", ""),
                ))

        tips.sort(key=lambda t: t.priority)
        return tips

    # ── Private: Utilities ────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str, default) -> dict | list:
        """
        Parse JSON from Gemini response, stripping markdown fences if present.
        Returns ``default`` on parse failure.
        """
        # Strip ```json ... ``` fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned.strip())

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from AI response: %r", raw[:100])
            return default
