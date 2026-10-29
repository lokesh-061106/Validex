"""Triage & Human Console (officers only).

Findings, rule outcomes, confidence metrics and audit data come from the database (PostgreSQL in
deployment); document files come from object storage (MinIO). Nothing here is reachable by institutions.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_application_for_user, require_official
from app.models.application import Application, ApplicationStatus
from app.models.finding_review import FindingReview, ReviewDecision
from app.models.user import User
from app.models.validation_result import ValidationResult
from app.schemas.application import ApplicationResponse
from app.schemas.validation import ValidationResultResponse
from app.services.audit_service import audit_service
from app.services.compliance_service import compliance_service
from app.services.graph_service import graph_service
from app.services.notification_service import notification_service
from app.services.rule_engine import AMBER, GREEN, RED
from app.services.triage_service import approval_blockers, red_status

router = APIRouter(prefix="/triage", tags=["Triage & Human Console (officers only)"])
Official = Annotated[User, Depends(require_official)]
DB = Annotated[Session, Depends(get_db)]


@router.get("/queue")
def triage_queue(db: DB, current_user: Official):
    """Applications ordered by unreviewed red items, then risk."""
    out = []
    query = db.query(Application).filter(Application.status != ApplicationStatus.DRAFT)
    if current_user.role.value in ("scrutiny", "expert", "approver"):
        query = query.filter(or_(Application.assigned_reviewer_id.is_(None),
                                 Application.assigned_reviewer_id == current_user.id))
    for app in query.order_by(desc(Application.risk_score)).all():
        rows = db.query(ValidationResult.rag, ValidationResult.actionable_by).filter(ValidationResult.application_id == app.id).all()
        s = red_status(db, app)
        out.append({
            "application": ApplicationResponse.model_validate(app).model_dump(mode="json"),
            "red": s["total"], "red_unreviewed": len(s["unreviewed"]), "red_confirmed": len(s["confirmed"]),
            "amber": sum(1 for r, _ in rows if r == AMBER),
            "amber_institution": sum(1 for r, a in rows if r == AMBER and a == "institution"),
        })
    out.sort(key=lambda x: (-x["red_unreviewed"], -x["application"]["risk_score"]))
    return out


@router.get("/{app_id}")
def triage_bundle(app_id: uuid.UUID, db: DB, current_user: Official):
    """Everything the split-screen review needs for one application."""
    app = get_application_for_user(db, app_id, current_user)
    outcomes = compliance_service.evaluate(db, app)
    s = red_status(db, app)
    findings = []
    for f in db.query(ValidationResult).filter(ValidationResult.application_id == app.id).all():
        item = ValidationResultResponse.model_validate(f).model_dump(mode="json")
        review = s["reviews"].get(f.fingerprint)
        item["review"] = ({"decision": review.decision.value, "reason": review.reason, "at": review.created_at.isoformat(),
                           "reviewer_id": str(review.reviewer_id)} if review else None)
        findings.append(item)
    order = {RED: 0, AMBER: 1, GREEN: 2}
    findings.sort(key=lambda x: (order.get(x.get("rag"), 3), x["check_type"]))
    docs = [{"id": str(d.id), "doc_type": d.doc_type.value, "filename": d.original_filename, "status": d.status.value,
             "mime_type": d.mime_type, "page_count": d.page_count, "uploaded_at": d.uploaded_at.isoformat(),
             "watermark": (d.custody or {}).get("watermark"), "original_sha256": d.content_hash,
             "stored_sha256": (d.custody or {}).get("stored_sha256")}
            for d in sorted(app.documents, key=lambda d: d.uploaded_at) if d.is_current]
    return {
        "application": ApplicationResponse.model_validate(app).model_dump(mode="json"),
        "rules": outcomes,
        "findings": findings,
        "documents": docs,
        "counts": {"green_rules": sum(1 for o in outcomes if o["rag"] == GREEN),
                   "amber": sum(1 for f in findings if f["rag"] == AMBER), "red": s["total"],
                   "red_unreviewed": len(s["unreviewed"])},
        "approval_blockers": approval_blockers(db, app),
        "clarification_candidates": [str(f.id) for f in notification_service.clarification_candidates(db, app)],
    }


class ReviewIn(BaseModel):
    decision: ReviewDecision
    reason: str = Field(min_length=10, max_length=1000)


@router.post("/{app_id}/findings/{finding_id}/review")
def review_finding(app_id: uuid.UUID, finding_id: uuid.UUID, body: ReviewIn, db: DB, current_user: Official):
    """Officer confirms a RED anomaly as genuine, or overrides it with a recorded reason."""
    app = get_application_for_user(db, app_id, current_user)
    f = db.query(ValidationResult).filter(ValidationResult.id == finding_id, ValidationResult.application_id == app.id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    if f.rag != RED:
        raise HTTPException(status_code=422, detail="Only red findings are confirmed or overridden")
    review = FindingReview(application_id=app.id, fingerprint=f.fingerprint, finding_text=f.finding,
                           decision=body.decision, reason=body.reason.strip(), reviewer_id=current_user.id)
    db.add(review)
    db.commit()
    audit_service.log_event(db=db, action="FINDING_REVIEWED", user_id=current_user.id, application_id=app.id,
                            details={"finding_id": str(f.id), "fingerprint": f.fingerprint, "decision": body.decision.value,
                                     "reason": body.reason.strip(), "check_type": f.check_type.value, "rule_code": f.rule_code})
    return {"decision": body.decision.value, "approval_blockers": approval_blockers(db, app)}


@router.get("/{app_id}/graph")
def collusion_graph(app_id: uuid.UUID, db: DB, current_user: Official):
    app = get_application_for_user(db, app_id, current_user)
    return graph_service.subgraph(db, app)
