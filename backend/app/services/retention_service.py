"""Data retention: purge stored files of decided applications after the retention period.

Metadata, hashes, findings and the audit ledger are kept (they hold no document images);
raw OCR text is removed together with the files (data minimisation).
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import storage
from app.models.application import Application, ApplicationStatus
from app.models.document import Document
from app.services.audit_service import audit_service
from app.services.document_service import evidence_object

DECIDED = [ApplicationStatus.APPROVED, ApplicationStatus.REJECTED]


def purge_expired(db: Session, user_id, dry_run: bool = True, retention_days: int | None = None) -> dict[str, Any]:
    days = retention_days if retention_days is not None else settings.RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    candidates = (
        db.query(Document)
        .join(Application, Document.application_id == Application.id)
        .filter(Application.status.in_(DECIDED), Application.decided_at.isnot(None),
                Application.decided_at < cutoff, Document.files_purged_at.is_(None))
        .all()
    )
    if not dry_run:
        for d in candidates:
            for obj in (d.storage_path, evidence_object(d, "evidence"), evidence_object(d, "ela"), evidence_object(d, "annotated")):
                try:
                    storage.delete(obj)
                except Exception:
                    pass
            data = dict(d.extracted_data or {})
            data.pop("raw_text_snippet", None)
            d.extracted_data = data
            d.files_purged_at = datetime.now(timezone.utc)
        db.commit()
    result = {"dry_run": dry_run, "retention_days": days, "cutoff": cutoff.isoformat(), "documents": len(candidates)}
    audit_service.log_event(db=db, action="RETENTION_PURGE" + ("_DRY_RUN" if dry_run else ""), user_id=user_id, details=result)
    return result
