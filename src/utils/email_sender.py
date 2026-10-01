"""
src/utils/email_sender.py
────────────────────────────────────────────────────────────────────────────────
Email Sender — sends job applications via SMTP with attached documents.

Supports Gmail (SMTP_SSL port 465) and any standard SMTP server.
All credentials are read exclusively from environment variables.

Security: Credentials never appear in source code, logs, or exception messages.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

from src.utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)


class EmailSenderError(Exception):
    """Raised when the email cannot be sent after all attempts."""


class EmailSender:
    """
    SMTP email sender for job applications.

    Reads credentials from environment:
      EMAIL_ADDRESS    — sender email (e.g. yourname@gmail.com)
      EMAIL_PASSWORD   — app password (NOT the account password)
      SMTP_HOST        — SMTP server (default: smtp.gmail.com)
      SMTP_PORT        — port (default: 465 for SSL)

    Parameters
    ----------
    sender_email:
        Override EMAIL_ADDRESS env-var.
    smtp_host:
        Override SMTP_HOST env-var.
    smtp_port:
        Override SMTP_PORT env-var.
    """

    def __init__(
        self,
        sender_email: str | None = None,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
    ) -> None:
        self._sender = sender_email or os.getenv("EMAIL_ADDRESS", "")
        self._password = os.getenv("EMAIL_PASSWORD", "")
        self._host = smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
        self._port = smtp_port or int(os.getenv("SMTP_PORT", "465"))

        if not self._sender:
            raise EmailSenderError(
                "EMAIL_ADDRESS is not set. Add it to your .env file."
            )
        if not self._password:
            raise EmailSenderError(
                "EMAIL_PASSWORD is not set. For Gmail, create an App Password at "
                "myaccount.google.com/apppasswords"
            )

    def send_application(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        attachments: list[Path] | None = None,
        cc: list[str] | None = None,
    ) -> bool:
        """
        Send a job application email with optional document attachments.

        Parameters
        ----------
        to_email:
            Recipient HR email address.
        subject:
            Email subject line.
        body_text:
            Plain-text email body (the cover letter or a brief intro).
        attachments:
            List of file paths to attach (CV, cover letter DOCX, etc.).
        cc:
            Optional CC addresses.

        Returns
        -------
        bool
            True if sent successfully.

        Raises
        ------
        EmailSenderError
            If the email cannot be sent.
        """
        logger.info("Preparing application email to: %s", to_email)

        msg = MIMEMultipart()
        msg["From"] = self._sender
        msg["To"] = to_email
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc)

        # Body
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        # Attachments
        for path in (attachments or []):
            self._attach_file(msg, path)

        # Send
        all_recipients = [to_email] + (cc or [])
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(self._host, self._port, context=context) as server:
                server.login(self._sender, self._password)
                server.sendmail(self._sender, all_recipients, msg.as_string())
            logger.info("Application email sent to %s ✓", to_email)
            return True
        except smtplib.SMTPAuthenticationError:
            raise EmailSenderError(
                "SMTP authentication failed. Check EMAIL_ADDRESS and EMAIL_PASSWORD. "
                "For Gmail, use an App Password, not your account password."
            )
        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailSenderError(f"Recipient refused: {to_email} — {exc}") from exc
        except smtplib.SMTPException as exc:
            raise EmailSenderError(f"SMTP error: {type(exc).__name__}") from exc

    @staticmethod
    def _attach_file(msg: MIMEMultipart, path: Path) -> None:
        """Attach a file to the MIME message."""
        if not path.exists():
            logger.warning("Attachment not found, skipping: %s", path)
            return

        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())

        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename={path.name}",
        )
        msg.attach(part)
        logger.debug("Attached file: %s (%d bytes)", path.name, path.stat().st_size)

    def build_application_subject(
        self, applicant_name: str, job_title: str, company_name: str
    ) -> str:
        """Return a professional subject line."""
        return (
            f"Candidature — {job_title} | {applicant_name}"
        )

    def build_email_body(
        self, cover_letter: str, applicant_name: str
    ) -> str:
        """
        Build the email body: brief intro + cover letter text.
        The cover letter is also attached as DOCX; this is the plain-text version.
        """
        intro = (
            f"Madame, Monsieur,\n\n"
            f"Veuillez trouver ci-joint ma candidature pour ce poste, "
            f"comprenant ma lettre de motivation et mon CV.\n\n"
            f"{'─' * 60}\n\n"
        )
        signature = (
            f"\n\n{'─' * 60}\n"
            f"Cordialement,\n{applicant_name}\n"
            f"(Documents complets joints en pièce jointe)"
        )
        return intro + cover_letter + signature
