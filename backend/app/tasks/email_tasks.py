from __future__ import annotations

import logging

from ..celery_app import celery_app
from ..services.email import send_email

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.email_tasks.send_email_task")
def send_email_task(to: str, subject: str, body_text: str) -> None:
    """
    Celery task wrapper around send_email.  Fire-and-forget — failures are
    logged but never retried automatically, since email is best-effort and
    a stuck retry queue should not impact game state.
    """
    send_email(to, subject, body_text)
