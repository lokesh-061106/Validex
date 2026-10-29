"""Light-queue tasks: issuing-authority verification with backoff retries and a periodic sweep."""

import uuid
from datetime import datetime, timezone

from app.core.celery_app import celery
from app.core.database import SessionLocal
from app.models.verification import Verification, VerificationStatus
from app.services.verification_service import verification_service


@celery.task(name="app.tasks.verification_tasks.verify_document_task")
def verify_document_task(document_id: str):
    db = SessionLocal()
    try:
        results = verification_service.verify_document(db, uuid.UUID(document_id))
        return [{"method": v.method.value, "status": v.status.value} for v in results]
    finally:
        db.close()


@celery.task(name="app.tasks.verification_tasks.retry_due_verifications")
def retry_due_verifications():
    """Re-run checks whose source was unavailable/pending and whose retry time has arrived."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due = (db.query(Verification.document_id)
               .filter(Verification.status.in_([VerificationStatus.UNAVAILABLE, VerificationStatus.PENDING]),
                       Verification.next_retry_at <= now)
               .distinct().all())
        for (doc_id,) in due:
            verify_document_task.delay(str(doc_id))
        return {"queued": len(due)}
    finally:
        db.close()
