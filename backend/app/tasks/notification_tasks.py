"""Light-queue task: deliver deficiency notices by email (in-app delivery is immediate)."""

from app.core.celery_app import celery
from app.services.notification_service import send_email


@celery.task(name="app.tasks.notification_tasks.send_deficiency_email", autoretry_for=(OSError,),
             retry_backoff=True, retry_jitter=True, max_retries=5)
def send_deficiency_email(recipient: str, subject: str, body: str):
    return {"sent": send_email(recipient, subject, body), "recipient": recipient}


@celery.task(name="app.tasks.notification_tasks.process_application_deadlines")
def process_application_deadlines():
    """Persistent deadline sweep; safe to repeat because each reminder/escalation level is stored."""
    from app.core.database import SessionLocal
    from app.services.deadline_service import process_due_deadlines as process

    db = SessionLocal()
    try:
        return process(db)
    finally:
        db.close()
