"""
main.py — JobAssist CLI Entry Point
────────────────────────────────────────────────────────────────────────────────
Demonstrates the full Phase 1 + 2 pipeline end-to-end:

  1. Initialise DB (creates jobassist.db with all tables)
  2. Seed a sample job listing into the database
  3. Call Gemini 2.5 Pro to generate a tailored cover letter
  4. Store the cover letter in an Application record
  5. Print a live dashboard of all jobs and applications

Run:
    PYTHONPATH=. .venv/bin/python main.py
"""
from __future__ import annotations
from dataclasses import dataclass

import sys
import textwrap
from datetime import UTC, datetime

from dotenv import load_dotenv

# ── Bootstrap: load .env before importing any src module ─────────────────────
load_dotenv()

from src.db.database import get_session, init_db          # noqa: E402
from src.db.models import Application, ApplicationStatus, Job  # noqa: E402
from src.db.repository import ApplicationRepository, JobRepository  # noqa: E402
from src.ai.document_tailor import DocumentTailor, DocumentTailorError  # noqa: E402
from src.utils.logger import configure_root_logger, get_logger  # noqa: E402


@dataclass
class JobSnapshot:
    """Plain-data snapshot of a Job row — safe to pass across session boundaries."""
    id: int
    title: str
    company: str
    location: str
    url: str
    source: str
    description: str

configure_root_logger()
logger = get_logger(__name__)

# ── ANSI colours ─────────────────────────────────────────────────────────────

CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# ── Sample data ───────────────────────────────────────────────────────────────

SAMPLE_JOB = dict(
    title="Senior Python Engineer",
    company="NovaTech AI",
    location="London, UK (Hybrid)",
    url="https://novatech.ai/careers/senior-python-engineer",
    source="linkedin",
    description=textwrap.dedent("""\
        We are looking for a Senior Python Engineer to join our AI Platform team.

        Requirements:
        - 5+ years of Python (3.10+) in production environments
        - Strong experience with FastAPI or Django REST Framework
        - Proficiency with PostgreSQL and SQLAlchemy ORM
        - Experience designing and deploying ML pipelines (MLflow, Kubeflow)
        - Familiarity with AWS (EC2, S3, Lambda) or GCP
        - Strong understanding of SOLID principles and design patterns
        - Experience writing unit and integration tests (pytest)
        - Excellent communication skills and ability to mentor junior engineers

        Nice to have:
        - Experience with LLM APIs (OpenAI, Google Gemini)
        - Contributions to open-source Python projects
        - Knowledge of Docker and Kubernetes

        Compensation: £90,000 – £120,000 + equity + benefits
    """),
)

MASTER_RESUME = textwrap.dedent("""\
    Abdelhak Mirbah
    Python Engineer | AI/ML Enthusiast
    abdelhak@example.com | github.com/AbdelhakMirbah | London, UK

    EXPERIENCE

    Python Backend Engineer — FinServe Ltd (2021 – Present)
    • Built and maintained FastAPI microservices serving 500K daily requests
    • Migrated monolith to event-driven architecture using Kafka and Celery
    • Reduced API latency by 40% through Redis caching and DB query optimisation
    • Designed SQLAlchemy ORM schemas and managed Alembic migrations
    • Led adoption of pytest across the team; achieved 85% test coverage
    • Mentored 3 junior engineers; conducted weekly code review sessions

    Junior Python Developer — DevCore Agency (2019 – 2021)
    • Developed Django REST Framework APIs for e-commerce clients
    • Integrated AWS S3 for media storage and Lambda for async processing
    • Wrote unit and integration tests; contributed to CI/CD pipeline setup

    SKILLS
    Python 3.10+, FastAPI, Django, SQLAlchemy, PostgreSQL, Redis
    AWS (S3, EC2, Lambda), Docker, pytest, Kafka, Celery
    SOLID principles, design patterns, code review, mentoring
    Google Gemini API, OpenAI API, LangChain

    EDUCATION
    BSc Computer Science — University of Manchester (2019)
""")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _banner(title: str) -> None:
    width = 70
    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}\n")


def _ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"  {YELLOW}›{RESET}  {msg}")


def _err(msg: str) -> None:
    print(f"  {RED}✗{RESET}  {msg}", file=sys.stderr)


# ── Pipeline steps ────────────────────────────────────────────────────────────

def step_init_db() -> None:
    _banner("Step 1 — Initialise Database")
    init_db()
    _ok("Database engine ready (WAL mode, FK enforcement ON)")
    _ok("Tables created: jobs, applications")


def step_seed_job() -> JobSnapshot:
    _banner("Step 2 — Seed Sample Job Listing")
    with get_session() as session:
        repo = JobRepository(session)
        job = Job(**SAMPLE_JOB)
        result = repo.add_or_ignore(job)

        if result is None:
            # Already exists — fetch it
            existing = repo.get_by_url(SAMPLE_JOB["url"])
            _info(f"Job already in DB (id={existing.id}) — using existing record.")
            snap = JobSnapshot(**{f: getattr(existing, f) for f in JobSnapshot.__dataclass_fields__})
        else:
            _ok(f"Job saved  →  id={result.id}")
            _ok(f"Title      :  {result.title}")
            _ok(f"Company    :  {result.company}")
            _ok(f"Source     :  {result.source}")
            snap = JobSnapshot(**{f: getattr(result, f) for f in JobSnapshot.__dataclass_fields__})

    return snap


def step_generate_cover_letter(job: JobSnapshot) -> str:
    _banner("Step 3 — Generate Tailored Cover Letter (Gemini 2.5 Pro Preview)")
    _info(f"Calling gemini-2.5-pro for job_id={job.id} …")

    tailor = DocumentTailor()          # reads GEMINI_API_KEY from .env

    try:
        docs = tailor.tailor(
            job_description=job.description,
            master_resume=MASTER_RESUME,
            applicant_name="Abdelhak Mirbah",
            company_name=job.company,
            job_title=job.title,
        )
    except DocumentTailorError as exc:
        _err(f"AI generation failed: {exc}")
        raise

    _ok("Cover letter generated ✓")
    _ok("Resume summary generated ✓")
    _ok(f"Keywords extracted ({len(docs.keywords)}): {', '.join(docs.keywords[:5])}…")

    print(f"\n{BOLD}── Cover Letter Preview ──{RESET}")
    preview = docs.cover_letter[:600].strip()
    for line in preview.splitlines():
        print(f"  {DIM}{line}{RESET}")
    if len(docs.cover_letter) > 600:
        print(f"  {DIM}… (truncated — full text saved to DB){RESET}")

    return docs.cover_letter


def step_save_application(job: JobSnapshot, cover_letter: str) -> int:
    """Persist the application and return its id."""
    _banner("Step 4 — Create Application Record in DB")
    with get_session() as session:
        app_repo = ApplicationRepository(session)

        # Check if an application already exists for this job
        existing_app = app_repo.get_by_job_id(job.id)
        if existing_app:
            app_id = existing_app.id
            _info(f"Application already exists (id={app_id}) — updating documents.")
            app_repo.save_documents(app_id, cover_letter=cover_letter)
            _ok(f"Cover letter updated on Application id={app_id}")
            return app_id

        app = Application(job_id=job.id, status=ApplicationStatus.PENDING)
        added = app_repo.add(app)
        app_repo.save_documents(added.id, cover_letter=cover_letter)
        app_id = added.id

        _ok(f"Application saved  →  id={app_id}")
        _ok(f"Status             :  {ApplicationStatus.PENDING.value}")
        _ok("Cover letter       :  stored in DB ✓")
        return app_id


def step_dashboard() -> None:
    _banner("Step 5 — Live Dashboard")
    with get_session() as session:
        jobs = JobRepository(session).list_all()
        apps = ApplicationRepository(session).list_all()

        print(f"  {BOLD}Jobs in database:{RESET}  {len(jobs)}")
        for j in jobs:
            print(f"    {DIM}[{j.id}]{RESET} {j.title} @ {j.company}  ({j.source})")

        print(f"\n  {BOLD}Applications:{RESET}  {len(apps)}")
        for a in apps:
            cl_len = len(a.cover_letter) if a.cover_letter else 0
            print(
                f"    {DIM}[{a.id}]{RESET} job_id={a.job_id}  "
                f"status={YELLOW}{a.status.value}{RESET}  "
                f"cover_letter={GREEN}{cl_len} chars{RESET}"
            )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\n{BOLD}{CYAN}{'═' * 70}")
    print("  J O B A S S I S T  —  Phase 1 & 2 Demo Runner")
    print(f"{'═' * 70}{RESET}\n")
    print(f"  {DIM}Python-powered job search automation with Gemini 2.5 Pro AI{RESET}")
    print(f"  {DIM}Started at: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}{RESET}\n")

    try:
        step_init_db()
        job          = step_seed_job()
        cover_letter = step_generate_cover_letter(job)
        step_save_application(job, cover_letter)
        step_dashboard()

        print(f"\n{BOLD}{GREEN}{'═' * 70}")
        print("  ✓  All steps completed successfully!")
        print(f"{'═' * 70}{RESET}\n")
        return 0

    except KeyboardInterrupt:
        print(f"\n{YELLOW}  Interrupted by user.{RESET}\n")
        return 130
    except Exception as exc:
        _err(f"Fatal error: {exc}")
        logger.exception("Unhandled exception in main()")
        return 1


if __name__ == "__main__":
    sys.exit(main())
