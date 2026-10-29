"""Documents: upload, replace (rectification), progress, evidence and page rendering."""

import io
import uuid
from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import (
    get_application_for_user, get_current_user, get_document_for_user, is_official, require_official, require_role,
)
from app.core.storage import storage
from app.models.application import ApplicationStatus
from app.models.document import Document, DocumentType
from app.models.user import User, UserRole
from app.schemas.document import DocumentDetailResponse, DocumentResponse
from app.schemas.validation import ValidationResultResponse
from app.schemas.verification import VerificationResponse
from app.services.audit_service import audit_service
from app.services.document_service import document_service, evidence_object
from app.schemas.portal import PortalDocument, portal_document

router = APIRouter(prefix="/documents", tags=["Documents"])

UPLOADABLE = {ApplicationStatus.DRAFT, ApplicationStatus.DEFICIENCY_FOUND}
require_institution = require_role([UserRole.INSTITUTION])


async def _read_limited(file: UploadFile) -> bytes:
    data = await file.read(settings.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_MB} MB")
    return data


@router.post("/upload", response_model=PortalDocument, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    application_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
    current_user: Annotated[User, Depends(require_institution)],
    db: Annotated[Session, Depends(get_db)],
    doc_type: Annotated[DocumentType | None, Form()] = None,
):
    """Institution uploads evidence (PDF/JPEG/PNG/GeoJSON, or MP4 lab walkthrough).

    The response is deliberately static ("received"): analysis runs privately afterwards and its
    results are visible only in the officers' console."""
    app = get_application_for_user(db, application_id, current_user)
    if app.status not in UPLOADABLE:
        raise HTTPException(status_code=409, detail="Documents can only be added while the application is a draft or under rectification")
    data = await _read_limited(file)
    doc = document_service.create_document(db, app, data, file.filename or "upload", current_user.id, doc_type)
    document_service.schedule_processing(db, doc.id, current_user.id, background_tasks)
    db.refresh(doc)
    return portal_document(doc)


@router.post("/{doc_id}/replace", response_model=PortalDocument, status_code=status.HTTP_201_CREATED)
async def replace_document(
    doc_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    current_user: Annotated[User, Depends(require_institution)],
    db: Annotated[Session, Depends(get_db)],
):
    """Rectification: upload a corrected version of one document. The previous version is kept for audit."""
    old = get_document_for_user(db, doc_id, current_user)
    if not old.is_current:
        raise HTTPException(status_code=409, detail="This document has already been replaced")
    app = get_application_for_user(db, old.application_id, current_user)
    if app.status not in UPLOADABLE:
        raise HTTPException(status_code=409, detail="Documents can only be replaced while the application is a draft or under rectification")
    data = await _read_limited(file)
    doc = document_service.create_document(db, app, data, file.filename or old.original_filename, current_user.id,
                                           old.doc_type, replaces=old)
    document_service.schedule_processing(db, doc.id, current_user.id, background_tasks)
    db.refresh(doc)
    return portal_document(doc)


@router.get("/{doc_id}", response_model=DocumentDetailResponse | PortalDocument)
def get_document(doc_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                 current_user: Annotated[User, Depends(get_current_user)]):
    doc = get_document_for_user(db, doc_id, current_user)
    if not is_official(current_user):
        return portal_document(doc)
    versions = (db.query(Document).filter(Document.application_id == doc.application_id, Document.doc_type == doc.doc_type)
                .order_by(Document.uploaded_at).all())
    base = DocumentResponse.model_validate(doc).model_dump()
    return DocumentDetailResponse(
        **base,
        verifications=[VerificationResponse.model_validate(v).model_dump(mode="json")
                       for v in sorted(doc.verifications, key=lambda v: v.verified_at, reverse=True)],
        findings=[ValidationResultResponse.model_validate(f).model_dump(mode="json") for f in doc.validation_results],
        versions=[{"id": str(v.id), "filename": v.original_filename, "uploaded_at": v.uploaded_at.isoformat(),
                   "is_current": v.is_current, "status": v.status.value} for v in versions],
    )


@router.get("/{doc_id}/status")
def get_processing_status(doc_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                          current_user: Annotated[User, Depends(require_official)]):
    """Officers only; institutions get no processing feedback."""
    doc = get_document_for_user(db, doc_id, current_user)
    return {"id": str(doc.id), "status": doc.status.value, "stage": doc.processing_stage,
            "progress": doc.processing_progress or 0, "doc_type": doc.doc_type.value}


@router.post("/{doc_id}/reprocess", response_model=DocumentResponse)
def reprocess(doc_id: uuid.UUID, background_tasks: BackgroundTasks, db: Annotated[Session, Depends(get_db)],
              current_user: Annotated[User, Depends(require_official)]):
    doc = get_document_for_user(db, doc_id, current_user)
    document_service.schedule_processing(db, doc.id, current_user.id, background_tasks)
    db.refresh(doc)
    return doc


def _log_view(db: Session, user: User, doc: Document, what: str) -> None:
    if is_official(user):
        audit_service.log_event(db=db, action="DOCUMENT_VIEWED", user_id=user.id, application_id=doc.application_id,
                                details={"document_id": str(doc.id), "view": what})


@router.get("/{doc_id}/file")
def get_document_file(doc_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                      current_user: Annotated[User, Depends(get_current_user)]):
    doc = get_document_for_user(db, doc_id, current_user)
    try:
        data = storage.get_bytes(doc.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="File is no longer stored (retention period ended)")
    _log_view(db, current_user, doc, "file")
    return Response(content=data, media_type=doc.mime_type,
                    headers={"Content-Disposition": f'inline; filename="{doc.original_filename}"',
                             "Cache-Control": "private, no-store"})


@router.get("/{doc_id}/page/{page}")
def render_page(doc_id: uuid.UUID, page: int, db: Annotated[Session, Depends(get_db)],
                current_user: Annotated[User, Depends(get_current_user)]):
    """PNG of one page (PDF) or the image itself, for the evidence overlay viewer."""
    import fitz
    from PIL import Image

    doc = get_document_for_user(db, doc_id, current_user)
    try:
        data = storage.get_bytes(doc.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="File is no longer stored")
    if doc.mime_type == "application/pdf":
        pdf = fitz.open(stream=data, filetype="pdf")
        if not 0 <= page < len(pdf):
            raise HTTPException(status_code=404, detail="Page out of range")
        png = pdf[page].get_pixmap(dpi=110).tobytes("png")
    elif doc.mime_type.startswith("image/"):
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((1400, 1400))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        png = buf.getvalue()
    else:
        raise HTTPException(status_code=415, detail="No page preview for this file type")
    _log_view(db, current_user, doc, f"page:{page}")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.get("/{doc_id}/custody")
def verify_custody(doc_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                   current_user: Annotated[User, Depends(require_official)]):
    """Re-verify the chain of custody of the stored (watermarked) object."""
    from app.services import custody_service
    doc = get_document_for_user(db, doc_id, current_user)
    if not doc.custody:
        return {"intact": False, "checks": {}, "note": "Stored before chain-of-custody watermarking was introduced"}
    try:
        stored = storage.get_bytes(doc.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="File is no longer stored (retention period ended)")
    result = custody_service.verify(stored, doc.custody.get("kind", ""), doc.custody)
    result["matches_stored_hash_at_intake"] = result["stored_sha256"] == doc.custody.get("stored_sha256")
    result["intact"] = result["intact"] and result["matches_stored_hash_at_intake"]
    audit_service.log_event(db=db, action="CUSTODY_VERIFIED", user_id=current_user.id, application_id=doc.application_id,
                            details={"document_id": str(doc.id), "intact": result["intact"]})
    return result


@router.get("/{doc_id}/evidence/{kind}")
def get_evidence_image(doc_id: uuid.UUID, kind: str, db: Annotated[Session, Depends(get_db)],
                       current_user: Annotated[User, Depends(require_official)]):
    """Annotated evidence images: 'evidence' (tamper boxes), 'ela' (ELA heatmap), 'annotated' (CV detections)."""
    if kind not in ("evidence", "ela", "annotated"):
        raise HTTPException(status_code=404, detail="Unknown evidence kind")
    doc = get_document_for_user(db, doc_id, current_user)
    try:
        data = storage.get_bytes(evidence_object(doc, kind))
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="No such evidence image")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
