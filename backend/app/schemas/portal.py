"""Institution-facing ("blind") views.

The college portal must not reveal AI forensic results, risk scores, verification outcomes or
processing stages, so institutions cannot probe or adapt to the detectors. These schemas expose
only what an institution legitimately needs: what it submitted, that it was received, the
checklist, the official workflow status, and clarification requests addressed to it.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.application import Application, ApplicationStatus, ApplicationCategory
from app.models.document import Document, DocumentType

PORTAL_STATUS = {
    ApplicationStatus.DRAFT: "draft",
    ApplicationStatus.SUBMITTED: "received",
    ApplicationStatus.UNDER_REVIEW: "under_review",
    ApplicationStatus.DEFICIENCY_FOUND: "clarification_requested",
    ApplicationStatus.VERIFIED: "under_review",
    ApplicationStatus.APPROVED: "approved",
    ApplicationStatus.REJECTED: "rejected",
}


class PortalDocument(BaseModel):
    id: UUID
    doc_type: DocumentType
    original_filename: str
    file_size: int
    uploaded_at: datetime
    is_current: bool
    state: str = "received"  # always static: no processing stage, no flags


class PortalApplication(BaseModel):
    id: UUID
    application_number: str
    institution_name: str
    permanent_id: str | None
    requested_intake: int | None
    category: ApplicationCategory
    academic_year: str
    status: str
    rectification_due: datetime | None
    submitted_at: datetime
    updated_at: datetime
    documents: list[PortalDocument] = []
    checklist: list[dict] = []


def portal_document(doc: Document) -> PortalDocument:
    return PortalDocument(id=doc.id, doc_type=doc.doc_type, original_filename=doc.original_filename,
                          file_size=doc.file_size, uploaded_at=doc.uploaded_at, is_current=doc.is_current)


def portal_application(app: Application, checklist: list[dict] | None = None, with_documents: bool = True) -> PortalApplication:
    return PortalApplication(
        id=app.id, application_number=app.application_number, institution_name=app.institution_name,
        permanent_id=app.permanent_id, requested_intake=app.requested_intake, category=app.category,
        academic_year=app.academic_year, status=PORTAL_STATUS[app.status], rectification_due=app.rectification_due,
        submitted_at=app.submitted_at, updated_at=app.updated_at,
        documents=[portal_document(d) for d in sorted(app.documents, key=lambda d: d.uploaded_at)] if with_documents else [],
        checklist=[{k: v for k, v in c.items() if k in ("doc_type", "title", "description")} for c in (checklist or [])],
    )
