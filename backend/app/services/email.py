from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..core.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body_text: str) -> None:
    """
    Send a plain-text email via SMTP.

    Silently returns without sending if SMTP is not configured — dev environments
    run without email credentials and should never raise on missing config.
    All exceptions are caught and logged so a mail failure never crashes a request.
    """
    if not settings.smtp_host or not settings.smtp_user:
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg.attach(MIMEText(body_text, "plain"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(msg["From"], [to], msg.as_string())
    except Exception:
        logger.exception("Failed to send email to %s (subject: %r)", to, subject)
