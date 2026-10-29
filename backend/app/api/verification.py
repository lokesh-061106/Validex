"""Issuing-authority verification endpoints."""

import uuid
from typing import Any
from pydantic import BaseModel, Field
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_db, get_document_for_user, require_official
from app.models.user import User
from app.models.verification import Verification
from app.schemas.verification import VerificationResponse
from app.services.verification_service import SOURCES, verification_service
from app.mock_authority.service import authority_name
from app.mock_authority.keys import sign_payload, parse_and_verify
from app.ml.qr_verifier import render_qr_png
from app.core.config import settings
from app.core.dependencies import require_admin
from app.services.audit_service import audit_service

router = APIRouter(prefix="/verification", tags=["Source Verification"])


class DemoQRRequest(BaseModel):
    issuer: str = Field(min_length=1, max_length=64)
    data: dict[str, Any]


@router.post("/demo-qr")
def generate_demo_qr(body: DemoQRRequest, current_user: Annotated[User, Depends(require_admin)],
                     db: Annotated[Session, Depends(get_db)]):
    """Render and verify a signed QR using deterministic DEMO issuer keys; disabled in production."""
    if settings.is_production:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    try:
        signed = sign_payload(body.issuer, body.data)
        verification = parse_and_verify(signed)
        image = render_qr_png(signed)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Demo QR generation failed: {exc}") from exc
    audit_service.log_event(db=db, action="DEMO_QR_GENERATED", user_id=current_user.id,
                            details={"issuer": body.issuer, "signature_valid": verification["signature_valid"],
                                     "simulated": True})
    return {"simulated": True, "label": "DEMO SIGNER — NOT AN OFFICIAL ISSUER",
            "payload": signed, "qr_png_base64": image,
            "verification": {"format_ok": verification["format_ok"],
                             "signature_valid": verification["signature_valid"],
                             "issuer": verification["issuer"]}}


@router.post("/trigger/{doc_id}", response_model=list[VerificationResponse], status_code=201)
def trigger_verification(doc_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                         current_user: Annotated[User, Depends(require_official)]):
    """Verify a document via its signed QR code (offline) and the issuing authority's records (API)."""
    doc = get_document_for_user(db, doc_id, current_user)
    return verification_service.verify_document(db, doc.id, user_id=current_user.id)


@router.get("/status/{doc_id}", response_model=list[VerificationResponse])
def get_verification_history(doc_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                             current_user: Annotated[User, Depends(require_official)]):
    doc = get_document_for_user(db, doc_id, current_user)
    return db.query(Verification).filter(Verification.document_id == doc.id).order_by(Verification.verified_at.desc()).all()


@router.get("/sources")
def list_sources(current_user: Annotated[User, Depends(get_current_user)]):
    """Which document types can be verified automatically, and against which source."""
    return [{"doc_type": dt.value, "source": authority_name(spec["authority"]), "identifier": spec["id_field"],
             "fields_compared": [c[0] for c in spec["compare"]]} for dt, spec in SOURCES.items()]
