"""
src/ai/document_generator.py
────────────────────────────────────────────────────────────────────────────────
DOCX Document Generator — uses python-docx to produce formatted Word documents
for cover letters and tailored resume summaries.

Outputs go to ``output/<job_id>/`` to keep all artefacts organised.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Inches
from docx.oxml import OxmlElement

from src.utils.logger import get_logger

logger = get_logger(__name__)

_OUTPUT_ROOT = Path("output")


def _set_run_font(run, name: str = "Calibri", size: int = 11, bold: bool = False,
                  color: RGBColor | None = None) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = color


def _add_horizontal_rule(doc: Document) -> None:
    """Add a light grey horizontal separator line."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "CCCCCC")
    pBdr.append(bottom)
    pPr.append(pBdr)


class DocumentGenerator:
    """
    Generates formatted Word (.docx) documents for job applications.

    Parameters
    ----------
    output_root:
        Base directory for all generated files.
        Default: ``./output/``
    """

    def __init__(self, output_root: str | Path = _OUTPUT_ROOT) -> None:
        self._root = Path(output_root)
        self._root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: int) -> Path:
        """Return (and create) the output directory for a specific job."""
        d = self._root / str(job_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── Cover Letter ─────────────────────────────────────────────────────────

    def generate_cover_letter(
        self,
        job_id: int,
        cover_letter_text: str,
        applicant_name: str,
        company_name: str,
        job_title: str,
    ) -> Path:
        """
        Generate a professionally formatted cover letter as .docx.

        Parameters
        ----------
        job_id:
            DB job ID — used to name the output directory.
        cover_letter_text:
            The AI-generated cover letter body text.
        applicant_name:
            Candidate's full name.
        company_name:
            Target employer name.
        job_title:
            Target role.

        Returns
        -------
        Path
            Absolute path to the generated .docx file.
        """
        doc = Document()

        # Page margins
        for section in doc.sections:
            section.top_margin = Inches(1.0)
            section.bottom_margin = Inches(1.0)
            section.left_margin = Inches(1.2)
            section.right_margin = Inches(1.2)

        # ── Header: Applicant name ────────────────────────────────────────
        name_para = doc.add_paragraph()
        name_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = name_para.add_run(applicant_name.upper())
        _set_run_font(run, size=16, bold=True, color=RGBColor(0x1A, 0x56, 0x96))

        # Date + job title subheader
        sub_para = doc.add_paragraph()
        sub_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        date_str = datetime.now(UTC).strftime("%B %d, %Y")
        sub_run = sub_para.add_run(f"Application for {job_title} | {date_str}")
        _set_run_font(sub_run, size=10, color=RGBColor(0x55, 0x55, 0x55))

        _add_horizontal_rule(doc)

        # ── Recipient line ────────────────────────────────────────────────
        recip = doc.add_paragraph()
        recip.paragraph_format.space_before = Pt(10)
        recip_run = recip.add_run(f"To the Hiring Team at {company_name},")
        _set_run_font(recip_run, size=11, bold=True)

        # ── Body paragraphs ───────────────────────────────────────────────
        paragraphs = [p.strip() for p in cover_letter_text.split("\n\n") if p.strip()]
        # Skip a leading salutation if the AI included one (we added our own)
        if paragraphs and (
            paragraphs[0].lower().startswith("dear")
            or paragraphs[0].lower().startswith("to the")
        ):
            paragraphs = paragraphs[1:]

        for para_text in paragraphs:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(0)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            run = p.add_run(para_text)
            _set_run_font(run, size=11)

        # ── Sign-off ──────────────────────────────────────────────────────
        _add_horizontal_rule(doc)
        signoff = doc.add_paragraph()
        signoff.paragraph_format.space_before = Pt(10)
        sign_run = signoff.add_run(f"Yours sincerely,\n{applicant_name}")
        _set_run_font(sign_run, size=11)

        # ── Save ──────────────────────────────────────────────────────────
        safe_company = "".join(c if c.isalnum() else "_" for c in company_name)
        filename = f"CoverLetter_{safe_company}_{job_title.replace(' ', '_')[:30]}.docx"
        path = self.job_dir(job_id) / filename
        doc.save(str(path))
        logger.info("Cover letter saved: %s", path)
        return path

    # ── Resume Summary ────────────────────────────────────────────────────────

    def generate_resume_summary(
        self,
        job_id: int,
        resume_summary_bullets: str,
        applicant_name: str,
        job_title: str,
        keywords: list[str] | None = None,
    ) -> Path:
        """
        Generate a tailored resume summary as .docx.

        Parameters
        ----------
        job_id:
            DB job ID.
        resume_summary_bullets:
            Bullet-point resume summary (each line starts with '• ').
        applicant_name:
            Candidate name for the document header.
        job_title:
            Target role — used in header.
        keywords:
            ATS keywords to highlight in bold.

        Returns
        -------
        Path
            Absolute path to the generated .docx file.
        """
        doc = Document()

        # Margins
        for section in doc.sections:
            section.top_margin = Inches(1.0)
            section.left_margin = Inches(1.2)
            section.right_margin = Inches(1.2)

        # Header
        h = doc.add_paragraph()
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = h.add_run(f"{applicant_name.upper()} — Tailored Resume Summary")
        _set_run_font(run, size=14, bold=True, color=RGBColor(0x1A, 0x56, 0x96))

        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub_run = sub.add_run(f"Optimised for: {job_title}")
        _set_run_font(sub_run, size=10, color=RGBColor(0x55, 0x55, 0x55))

        _add_horizontal_rule(doc)

        # Bullets
        kw_set = {kw.lower() for kw in (keywords or [])}
        for line in resume_summary_bullets.splitlines():
            line = line.strip()
            if not line:
                continue
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_before = Pt(4)
            # Highlight keywords in bold
            words = line.lstrip("•·- ").split()
            for i, word in enumerate(words):
                run = p.add_run(word)
                if word.lower().rstrip(".,;:") in kw_set:
                    _set_run_font(run, size=11, bold=True)
                else:
                    _set_run_font(run, size=11)
                if i < len(words) - 1:
                    p.add_run(" ")

        # ATS Keywords section
        if keywords:
            _add_horizontal_rule(doc)
            kw_para = doc.add_paragraph()
            kw_label = kw_para.add_run("ATS Keywords: ")
            _set_run_font(kw_label, size=10, bold=True)
            kw_val = kw_para.add_run(", ".join(keywords))
            _set_run_font(kw_val, size=10, color=RGBColor(0x33, 0x33, 0x99))

        safe_title = job_title.replace(" ", "_")[:30]
        filename = f"ResumeSum_{safe_title}.docx"
        path = self.job_dir(job_id) / filename
        doc.save(str(path))
        logger.info("Resume summary saved: %s", path)
        return path
