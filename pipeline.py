"""
pipeline.py — JobAssist Full Automation Pipeline
────────────────────────────────────────────────────────────────────────────────
End-to-end automation:

  STEP 1  Scrape job offers  →  Indeed + LinkedIn (concurrent)
  STEP 2  Analyse each job   →  CV match score, requirements, HR email, tips
  STEP 3  Generate documents →  Tailored cover letter + resume summary (.docx)
  STEP 4  Email application  →  Send CV + cover letter to HR (optional)
  STEP 5  Dashboard          →  Ranked results with all intelligence

Usage:
    PYTHONPATH=. .venv/bin/python pipeline.py \
        --query "Développeur Python Senior" \
        --location "Paris" \
        --max 10 \
        --send-emails          # optional: auto-send to HR

    PYTHONPATH=. .venv/bin/python pipeline.py --help
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.db.database import get_session, init_db                # noqa: E402
from src.db.models import Application, ApplicationStatus, Job   # noqa: E402
from src.db.repository import ApplicationRepository, JobRepository  # noqa: E402
from src.ai.document_tailor import DocumentTailor, DocumentTailorError  # noqa: E402
from src.ai.document_generator import DocumentGenerator         # noqa: E402
from src.ai.job_analyzer import JobAnalyzer, JobAnalysis        # noqa: E402
from src.scrapers.indeed_scraper import IndeedScraper           # noqa: E402
from src.scrapers.linkedin_scraper import LinkedInScraper       # noqa: E402
from src.scrapers.scraper_engine import ScraperEngine           # noqa: E402
from src.utils.email_sender import EmailSender, EmailSenderError  # noqa: E402
from src.utils.logger import configure_root_logger, get_logger  # noqa: E402

configure_root_logger()
logger = get_logger(__name__)

# ── ANSI ─────────────────────────────────────────────────────────────────────
C = {
    "cyan":   "\033[96m",  "green":  "\033[92m",
    "yellow": "\033[93m",  "red":    "\033[91m",
    "blue":   "\033[94m",  "bold":   "\033[1m",
    "dim":    "\033[2m",   "reset":  "\033[0m",
}

def c(color: str, text: str) -> str:
    return f"{C[color]}{text}{C['reset']}"

def banner(title: str) -> None:
    w = 72
    print(f"\n{c('bold', c('cyan', '─' * w))}")
    print(c("bold", f"  {title}"))
    print(c("bold", c("cyan", "─" * w)) + "\n")

def ok(msg: str) -> None:
    print(f"  {c('green', '✓')}  {msg}")

def info(msg: str) -> None:
    print(f"  {c('yellow', '›')}  {msg}")

def err(msg: str) -> None:
    print(f"  {c('red', '✗')}  {msg}", file=sys.stderr)

def score_bar(score: int, width: int = 20) -> str:
    filled = int(width * score / 100)
    color = "green" if score >= 70 else "yellow" if score >= 45 else "red"
    bar = "█" * filled + "░" * (width - filled)
    return f"{c(color, bar)} {c('bold', str(score))}%"

# ── CV (hardcoded here — in production, load from file) ─────────────────────

MASTER_CV = textwrap.dedent("""\
    Abdelhak Mirbah
    Développeur Python | IA & Automatisation
    abdelhak@example.com | github.com/AbdelhakMirbah | Paris, France

    EXPÉRIENCE

    Ingénieur Python Backend — FinServe Ltd (2021–Présent)
    • API FastAPI servant 500K requêtes/jour
    • Migration monolithe → architecture événementielle (Kafka, Celery)
    • Réduction latence API de 40% via cache Redis et optimisation DB
    • Schémas SQLAlchemy ORM, migrations Alembic
    • Couverture tests pytest à 85%
    • Mentorat de 3 développeurs juniors

    Développeur Python Junior — DevCore Agency (2019–2021)
    • APIs Django REST Framework pour clients e-commerce
    • Intégration AWS S3 (stockage) et Lambda (traitement async)

    COMPÉTENCES
    Python 3.11+, FastAPI, Django, SQLAlchemy, PostgreSQL, Redis
    AWS (S3, EC2, Lambda), Docker, pytest, Kafka, Celery
    Google Gemini API, LangChain, Playwright, BeautifulSoup

    FORMATION
    Licence Informatique — Université Paris-Saclay (2019)
""")

APPLICANT_NAME = "Abdelhak Mirbah"
APPLICANT_EMAIL = "abdelhak@example.com"


# ── Pipeline Steps ────────────────────────────────────────────────────────────

async def step_scrape(query: str, location: str, max_per_source: int) -> list[Job]:
    banner(f"STEP 1 — Scraping job offers: '{query}' in '{location}'")
    info("Sources: Indeed (httpx) + LinkedIn (Playwright) — running concurrently…")

    engine = ScraperEngine(scrapers=[
        IndeedScraper(),
        LinkedInScraper(headless=True),
    ])
    jobs = await engine.run(query=query, location=location, max_per_source=max_per_source)

    if not jobs:
        info("No new jobs found (all may already be in DB).")
    else:
        ok(f"{len(jobs)} new job offers scraped and saved to database")
        for j in jobs[:5]:
            print(f"    {c('dim', f'[{j.id}]')} {j.title} @ {j.company} ({j.source})")
        if len(jobs) > 5:
            info(f"  … and {len(jobs) - 5} more")

    return jobs


def step_analyse(jobs: list[Job], send_emails: bool) -> list[tuple[Job, JobAnalysis]]:
    banner("STEP 2 — AI Analysis: CV match scoring + HR email + tips")

    if not jobs:
        info("No jobs to analyse.")
        return []

    tailor = DocumentTailor()
    analyzer = JobAnalyzer(tailor=tailor)
    results: list[tuple[Job, JobAnalysis]] = []

    for job in jobs:
        # Load full description from DB (may be a snapshot)
        with get_session() as session:
            db_job = JobRepository(session).get_by_id(job.id)
            description = db_job.description if db_job else ""
            company = db_job.company if db_job else job.company

        info(f"Analysing: {job.title} @ {company}…")
        try:
            analysis = analyzer.analyse(
                job_description=description or f"{job.title} at {company}",
                master_resume=MASTER_CV,
                company_name=company,
            )
            results.append((job, analysis))
            score_display = score_bar(analysis.match_score)
            hr = c("green", analysis.hr_email) if analysis.hr_email else c("dim", "not found")
            print(f"    Match: {score_display}  |  HR: {hr}")
        except DocumentTailorError as exc:
            err(f"Analysis failed for job {job.id}: {exc}")

    # Sort by match score DESC
    results.sort(key=lambda r: r[1].match_score, reverse=True)
    ok(f"Analysis complete for {len(results)} jobs — sorted by match score ↓")
    return results


def step_generate_documents(
    results: list[tuple[Job, JobAnalysis]],
) -> list[tuple[Job, JobAnalysis, dict[str, Path]]]:
    banner("STEP 3 — Generating Tailored Documents (.docx)")

    gen = DocumentGenerator()
    tailor = DocumentTailor()
    enriched = []

    for job, analysis in results:
        paths: dict[str, Path] = {}
        info(f"Generating docs for: {job.title} @ {job.company} (score={analysis.match_score}%)")

        with get_session() as session:
            db_job = JobRepository(session).get_by_id(job.id)
            description = db_job.description if db_job else ""

        try:
            # Tailored cover letter text
            docs = tailor.tailor(
                job_description=description or f"{job.title}",
                master_resume=MASTER_CV,
                applicant_name=APPLICANT_NAME,
                company_name=job.company,
                job_title=job.title,
            )

            # Cover letter DOCX
            cl_path = gen.generate_cover_letter(
                job_id=job.id,
                cover_letter_text=docs.cover_letter,
                applicant_name=APPLICANT_NAME,
                company_name=job.company,
                job_title=job.title,
            )
            paths["cover_letter"] = cl_path

            # Resume summary DOCX
            rs_path = gen.generate_resume_summary(
                job_id=job.id,
                resume_summary_bullets=docs.resume_summary,
                applicant_name=APPLICANT_NAME,
                job_title=job.title,
                keywords=docs.keywords,
            )
            paths["resume_summary"] = rs_path

            # Save to DB
            with get_session() as session:
                app_repo = ApplicationRepository(session)
                existing = app_repo.get_by_job_id(job.id)
                if existing:
                    app_repo.save_documents(
                        existing.id,
                        cover_letter=docs.cover_letter,
                        tailored_resume=docs.resume_summary,
                    )
                else:
                    app = Application(job_id=job.id, status=ApplicationStatus.PENDING)
                    app_repo.add(app)
                    app_repo.save_documents(
                        app.id,
                        cover_letter=docs.cover_letter,
                        tailored_resume=docs.resume_summary,
                    )

            ok(f"  Cover letter → {cl_path.name}")
            ok(f"  Resume summary → {rs_path.name}")

        except DocumentTailorError as exc:
            err(f"  Document generation failed: {exc}")

        enriched.append((job, analysis, paths))

    return enriched


def step_send_emails(
    enriched: list[tuple[Job, JobAnalysis, dict[str, Path]]],
) -> None:
    banner("STEP 4 — Sending Application Emails")

    try:
        sender = EmailSender()
    except EmailSenderError as exc:
        err(f"Email sender not configured: {exc}")
        info("Add EMAIL_ADDRESS and EMAIL_PASSWORD to your .env to enable auto-send.")
        return

    for job, analysis, paths in enriched:
        if not analysis.hr_email:
            info(f"Skipping {job.title} @ {job.company} — no HR email found")
            continue

        attachments = [p for p in paths.values() if p.exists()]

        # Load cover letter text from DB
        with get_session() as session:
            app = ApplicationRepository(session).get_by_job_id(job.id)
            cl_text = app.cover_letter if app else ""

        subject = sender.build_application_subject(APPLICANT_NAME, job.title, job.company)
        body = sender.build_email_body(cl_text or "", APPLICANT_NAME)

        try:
            sent = sender.send_application(
                to_email=analysis.hr_email,
                subject=subject,
                body_text=body,
                attachments=attachments,
            )
            if sent:
                ok(f"Sent to {analysis.hr_email} — {job.title} @ {job.company}")
                # Update status to APPLIED
                with get_session() as session:
                    app_repo = ApplicationRepository(session)
                    app = app_repo.get_by_job_id(job.id)
                    if app:
                        app_repo.update_status(app.id, ApplicationStatus.APPLIED)
        except EmailSenderError as exc:
            err(f"Failed to send to {analysis.hr_email}: {exc}")


def step_dashboard(results: list[tuple[Job, JobAnalysis, dict[str, Path]]]) -> None:
    banner("STEP 5 — Ranked Dashboard")

    if not results:
        info("No results to display.")
        return

    print(f"  {'#':<4} {'Score':<8} {'Title':<35} {'Company':<22} {'HR Email'}")
    print(f"  {'─'*4} {'─'*8} {'─'*35} {'─'*22} {'─'*25}")

    for rank, (job, analysis, paths) in enumerate(results, 1):
        score_col = c("green", f"{analysis.match_score}%") if analysis.match_score >= 70 \
               else c("yellow", f"{analysis.match_score}%") if analysis.match_score >= 45 \
               else c("red", f"{analysis.match_score}%")
        title = job.title[:33]
        company = job.company[:20]
        hr = analysis.hr_email or c("dim", "—")
        print(f"  {rank:<4} {score_col:<17} {title:<35} {company:<22} {hr}")

    print()
    # Show top job tips
    if results:
        top_job, top_analysis, _ = results[0]
        print(c("bold", f"\n  🏆 Top Match: {top_job.title} @ {top_job.company} ({top_analysis.match_score}%)"))
        if top_analysis.tips:
            print(c("bold", "\n  📋 Application Tips (personalised):"))
            for tip in top_analysis.tips[:4]:
                print(f"\n  {c('cyan', f'[{tip.category}]')} Priority {tip.priority}")
                print(f"    {c('bold', tip.tip)}")
                print(f"    {c('dim', tip.reason)}")

    # Document paths
    print(c("bold", "\n  📁 Generated Documents:"))
    for job, _, paths in results[:3]:
        if paths:
            print(f"\n  {c('dim', f'Job {job.id}:')} {job.title}")
            for doc_type, path in paths.items():
                print(f"    {c('green', '→')} {c('dim', str(path))}")


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="JobAssist — Full AI-powered job application pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python pipeline.py --query "Python Engineer" --location "Paris" --max 10
              python pipeline.py --query "Data Scientist" --location "Lyon" --send-emails
              python pipeline.py --query "Développeur Backend" --location "Remote France" --max 5
        """),
    )
    p.add_argument("--query", default="Développeur Python Senior",
                   help="Job search keywords (default: 'Développeur Python Senior')")
    p.add_argument("--location", default="Paris, France",
                   help="Location to search (default: 'Paris, France')")
    p.add_argument("--max", type=int, default=10,
                   help="Max results per source (default: 10)")
    p.add_argument("--send-emails", action="store_true",
                   help="Auto-send applications to found HR emails")
    p.add_argument("--skip-scrape", action="store_true",
                   help="Skip scraping — use jobs already in DB")
    p.add_argument("--min-score", type=int, default=0,
                   help="Minimum match score to generate documents for (default: 0)")
    return p.parse_args()


async def main_async(args: argparse.Namespace) -> int:
    print(f"\n{c('bold', c('cyan', '═' * 72))}")
    print(c("bold", "  J O B A S S I S T  —  Full Automation Pipeline"))
    print(c("bold", c("cyan", "═" * 72)) + "\n")

    # Init DB
    init_db()
    ok("Database ready")

    # Step 1: Scrape
    if args.skip_scrape:
        info("Scraping skipped — loading jobs from database")
        with get_session() as session:
            jobs = list(JobRepository(session).list_all())
        ok(f"Loaded {len(jobs)} jobs from database")
    else:
        jobs = await step_scrape(args.query, args.location, args.max)

    if not jobs:
        info("No jobs available. Try different search terms.")
        return 0

    # Step 2: Analyse
    results_raw = step_analyse(jobs, send_emails=args.send_emails)

    # Filter by minimum score
    if args.min_score > 0:
        results_raw = [(j, a) for j, a in results_raw if a.match_score >= args.min_score]
        info(f"After min-score filter ({args.min_score}%): {len(results_raw)} jobs remain")

    # Step 3: Generate documents
    enriched = step_generate_documents(results_raw)

    # Step 4: Send emails (optional)
    if args.send_emails:
        step_send_emails(enriched)
    else:
        info("Email sending skipped (use --send-emails to enable)")

    # Step 5: Dashboard
    step_dashboard(enriched)

    print(f"\n{c('bold', c('green', '═' * 72))}")
    print(c("bold", c("green", "  ✓  Pipeline complete!")))
    print(c("bold", c("green", "═" * 72)) + "\n")
    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print(f"\n{c('yellow', '  Interrupted by user.')}\n")
        return 130
    except Exception as exc:
        err(f"Fatal: {exc}")
        logger.exception("Unhandled exception in pipeline")
        return 1


if __name__ == "__main__":
    sys.exit(main())
