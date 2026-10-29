"""Heavy-queue task: run the full document pipeline (OCR, extraction, forensics, CV, verification)."""

import uuid

from app.core.celery_app import celery
from app.core.database import SessionLocal
from app.services.document_service import document_service


@celery.task(bind=True, name="app.tasks.document_tasks.process_document_task", max_retries=2,
             autoretry_for=(ConnectionError,), retry_backoff=True, retry_jitter=True)
def process_document_task(self, document_id: str, user_id: str | None = None):
    db = SessionLocal()
    try:
        doc = document_service.process_document(db, uuid.UUID(document_id), uuid.UUID(user_id) if user_id else None)
        return {"document_id": document_id, "status": doc.status.value}
    finally:
        db.close()
