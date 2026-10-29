"""Applications: institution drafting/submission and official decisions (human-in-the-loop)."""

import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_application_for_user, get_current_user, is_official, require_official, require_role
from app.models.application import AIRecommendation, Application, ApplicationCategory, ApplicationStatus
from app.models.document import DocumentStatus
from app.models.user import User, UserRole
from app.schemas.application import (
    ApplicationAssignmentUpdate, ApplicationCreate, ApplicationDecision, ApplicationDetailResponse, ApplicationResponse, DeficiencyNoticeRequest,
)
from app.schemas.document import DocumentResponse
from app.schemas.notification import NotificationResponse
from app.schemas.validation import ValidationResultResponse
from app.services.audit_service import audit_service
from app.services.compliance_service import compliance_service
from app.services.notification_service import notification_service
from app.services.validation_service import validation_service
from app.schemas.portal import PortalApplication, portal_application
from app.services.workflow_service import can_issue_final_decision, transition_allowed

router = APIRouter(prefix="/applications", tags=["Applications"])

EDITABLE = {ApplicationStatus.DRAFT, ApplicationStatus.DEFICIENCY_FOUND}
ADVERSE = {ApplicationStatus.REJECTED, ApplicationStatus.DEFICIENCY_FOUND}
require_institution = require_role([UserRole.INSTITUTION])


def _new_number(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    while True:
        number = f"AICTE-{year}-{secrets.randbelow(900000) + 100000}"
        if not db.query(Application).filter(Application.application_number == number).first():
            return number


@router.post("", response_model=PortalApplication, status_code=status.HTTP_201_CREATED)
def create_application(app_in: ApplicationCreate, current_user: Annotated[User, Depends(require_institution)],
                       db: Annotated[Session, Depends(get_db)]):
    """Institution starts a draft application. Officials do not see drafts until submitted."""
    app = Application(
        application_number=_new_number(db), institution_id=current_user.id,
        institution_name=current_user.institution_name or current_user.full_name,
        permanent_id=app_in.permanent_id, requested_intake=app_in.requested_intake,
        category=app_in.category, academic_year=app_in.academic_year, status=ApplicationStatus.DRAFT,
        ai_recommendation=AIRecommendation.PENDING,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    audit_service.log_event(db=db, action="APPLICATION_CREATED", user_id=current_user.id, application_id=app.id,
                            details={"application_number": app.application_number, "category": app.category.value})
    return portal_application(app, compliance_service.checklist(db, app))


@router.get("", response_model=list[ApplicationResponse] | list[PortalApplication])
def list_applications(
    db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(get_current_user)],
    status: ApplicationStatus | None = Query(None), category: ApplicationCategory | None = Query(None),
    search: str | None = Query(None, max_length=100), skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
):
    query = db.query(Application)
    if current_user.role == UserRole.INSTITUTION:
        query = query.filter(Application.institution_id == current_user.id)
    else:
        if current_user.role in (UserRole.SCRUTINY, UserRole.EXPERT, UserRole.APPROVER):
            query = query.filter(or_(Application.assigned_reviewer_id.is_(None),
                                     Application.assigned_reviewer_id == current_user.id))
        if status is None:
            query = query.filter(Application.status != ApplicationStatus.DRAFT)
    if status:
        query = query.filter(Application.status == status)
    if category:
        query = query.filter(Application.category == category)
    if search:
        like = f"%{search}%"
        query = query.filter(Application.institution_name.ilike(like) | Application.application_number.ilike(like))
    apps = query.order_by(desc(Application.risk_score), desc(Application.submitted_at)).offset(skip).limit(limit).all()
    if current_user.role == UserRole.INSTITUTION:
        return [portal_application(a, with_documents=False) for a in apps]
    return [ApplicationResponse.model_validate(a) for a in apps]


@router.get("/reviewers")
def list_reviewers(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(get_current_user)]):
    """Return only fields required for supervisor assignment controls."""
    if current_user.role not in (UserRole.SUPERVISOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Only supervisors can manage review assignments")
    users = db.query(User).filter(User.is_active.is_(True), User.role.in_(
        [UserRole.SCRUTINY, UserRole.EXPERT, UserRole.APPROVER])).order_by(User.full_name).all()
    return [{"id": str(u.id), "full_name": u.full_name, "role": u.role.value} for u in users]


@router.patch("/{app_id}/assignment", response_model=ApplicationResponse)
def assign_application(app_id: uuid.UUID, body: ApplicationAssignmentUpdate, db: Annotated[Session, Depends(get_db)],
                       current_user: Annotated[User, Depends(get_current_user)]):
    """Supervisors reassign submitted applications; changes are recorded in the audit ledger."""
    if current_user.role not in (UserRole.SUPERVISOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Only supervisors can assign application reviews")
    app = get_application_for_user(db, app_id, current_user)
    if app.status == ApplicationStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Draft applications cannot be assigned")
    assignee = None
    if body.assigned_to:
        assignee = db.query(User).filter(User.id == body.assigned_to, User.is_active.is_(True)).first()
        if not assignee or assignee.role not in (UserRole.SCRUTINY, UserRole.EXPERT, UserRole.APPROVER):
            raise HTTPException(status_code=422, detail="Assignment requires an active reviewer or approving officer")
    previous = str(app.assigned_reviewer_id) if app.assigned_reviewer_id else None
    app.assigned_reviewer_id = assignee.id if assignee else None
    app.assigned_by = current_user.id
    app.assigned_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(app)
    audit_service.log_event(db=db, action="APPLICATION_ASSIGNED", user_id=current_user.id, application_id=app.id,
                            details={"previous_assignee": previous, "assigned_to": str(assignee.id) if assignee else None,
                                     "reason": body.reason.strip()})
    return app


@router.get("/{app_id}", response_model=ApplicationDetailResponse | PortalApplication)
def get_application(app_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                    current_user: Annotated[User, Depends(get_current_user)]):
    app = get_application_for_user(db, app_id, current_user)
    if not is_official(current_user):
        return portal_application(app, compliance_service.checklist(db, app))
    if app.status == ApplicationStatus.DRAFT:
        raise HTTPException(status_code=404, detail="Application not found")
    current = [d for d in app.documents if d.is_current]
    base = ApplicationResponse.model_validate(app).model_dump()
    return ApplicationDetailResponse(
        **base,
        documents=[DocumentResponse.model_validate(d) for d in sorted(app.documents, key=lambda d: d.uploaded_at)],
        validation_results=[ValidationResultResponse.model_validate(v) for v in app.validation_results],
        checklist=compliance_service.checklist(db, app),
        total_documents=len(current),
        pending_documents=sum(1 for d in current if d.status in (DocumentStatus.PENDING, DocumentStatus.PROCESSING)),
        flagged_documents=sum(1 for d in current if d.status == DocumentStatus.FLAGGED),
    )


@router.patch("/{app_id}", response_model=PortalApplication)
def update_draft(app_id: uuid.UUID, app_in: ApplicationCreate, db: Annotated[Session, Depends(get_db)],
                 current_user: Annotated[User, Depends(require_institution)]):
    app = get_application_for_user(db, app_id, current_user)
    if app.status not in EDITABLE:
        raise HTTPException(status_code=409, detail="Application can only be edited while in draft or rectification")
    app.permanent_id, app.requested_intake = app_in.permanent_id, app_in.requested_intake
    app.category, app.academic_year = app_in.category, app_in.academic_year
    db.commit()
    audit_service.log_event(db=db, action="APPLICATION_EDITED", user_id=current_user.id, application_id=app.id,
                            details=app_in.model_dump(mode="json"))
    return portal_application(app, compliance_service.checklist(db, app))


@router.post("/{app_id}/submit", response_model=PortalApplication)
def submit_application(app_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                       current_user: Annotated[User, Depends(require_institution)]):
    """Submit (or resubmit after rectification). Runs AI pre-screening for the official queue."""
    app = get_application_for_user(db, app_id, current_user)
    if app.status not in EDITABLE:
        raise HTTPException(status_code=409, detail=f"Cannot submit an application in status '{app.status.value}'")
    if not transition_allowed(db, app.status, ApplicationStatus.SUBMITTED, current_user.role):
        raise HTTPException(status_code=409, detail="This workflow transition is not enabled for your role")
    if any(d.status in (DocumentStatus.PENDING, DocumentStatus.PROCESSING) for d in app.documents if d.is_current):
        raise HTTPException(status_code=409, detail="Documents are still being received; please submit again in a minute")
    previous = app.status
    app.status = ApplicationStatus.SUBMITTED
    app.submitted_at = datetime.now(timezone.utc)
    db.commit()
    audit_service.log_event(db=db, action="APPLICATION_SUBMITTED" if previous == ApplicationStatus.DRAFT else "APPLICATION_RESUBMITTED",
                            user_id=current_user.id, application_id=app.id, details={"from": previous.value})
    validation_service.validate_application(db, app.id, user_id=current_user.id)
    db.refresh(app)
    return portal_application(app, compliance_service.checklist(db, app))


@router.post("/{app_id}/decision", response_model=ApplicationResponse)
def record_decision(app_id: uuid.UUID, decision: ApplicationDecision, db: Annotated[Session, Depends(get_db)],
                    current_user: Annotated[User, Depends(require_official)]):
    """Official decision. The AI recommendation is advisory: overriding it, or any adverse decision,
    requires a written reason that is stored in the audit ledger."""
    app = get_application_for_user(db, app_id, current_user)
    if app.status == ApplicationStatus.DRAFT or decision.status in (ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED):
        raise HTTPException(status_code=409, detail="Invalid status transition")
    notes = (decision.verdict_notes or "").strip()
    ai_adverse = app.ai_recommendation in (AIRecommendation.DEFICIENCY, AIRecommendation.INSPECTION)
    override = (decision.status == ApplicationStatus.APPROVED and ai_adverse) or (
        decision.status in ADVERSE and app.ai_recommendation == AIRecommendation.FORWARD)
    if (decision.status in ADVERSE or override) and len(notes) < 10:
        raise HTTPException(status_code=422, detail="A written reason (at least 10 characters) is required for adverse "
                                                    "decisions and for decisions that differ from the AI recommendation")
    if decision.status in (ApplicationStatus.APPROVED, ApplicationStatus.REJECTED) and not can_issue_final_decision(current_user.role):
        raise HTTPException(status_code=403, detail="Final decisions require an assigned approving officer; platform administrators cannot issue statutory decisions")
    if decision.status == ApplicationStatus.APPROVED and any(
            d.status in (DocumentStatus.PENDING, DocumentStatus.PROCESSING) for d in app.documents if d.is_current):
        raise HTTPException(status_code=409, detail="Documents are still being processed")
    if not transition_allowed(db, app.status, decision.status, current_user.role):
        raise HTTPException(status_code=409, detail=f"Workflow transition {app.status.value} → {decision.status.value} is not enabled for your role")
    if decision.status in (ApplicationStatus.APPROVED, ApplicationStatus.VERIFIED):
        from app.services.triage_service import approval_blockers
        blockers = approval_blockers(db, app)
        if blockers:
            raise HTTPException(status_code=409, detail="Cannot approve: " + "; ".join(blockers))

    old = app.status
    app.status = decision.status
    app.overall_verdict = notes or app.overall_verdict
    app.decided_by, app.decided_at = current_user.id, datetime.now(timezone.utc)
    db.commit()
    db.refresh(app)
    audit_service.log_event(
        db=db, action="APPLICATION_DECISION", user_id=current_user.id, application_id=app.id,
        details={"from": old.value, "to": app.status.value, "notes": notes,
                 "ai_recommendation": app.ai_recommendation.value if app.ai_recommendation else None,
                 "ai_risk_score": app.risk_score, "overrides_ai": override},
    )
    return app


@router.post("/{app_id}/clarification-request", response_model=NotificationResponse, status_code=201)
def request_clarification(app_id: uuid.UUID, body: DeficiencyNoticeRequest, db: Annotated[Session, Depends(get_db)],
                          current_user: Annotated[User, Depends(require_official)]):
    """Send AMBER items (missing / expired / unreadable) to the institution as an encrypted request.
    RED anomalies are never sent; officers resolve them in the console."""
    app = get_application_for_user(db, app_id, current_user)
    if app.status in (ApplicationStatus.DRAFT, ApplicationStatus.APPROVED, ApplicationStatus.REJECTED):
        raise HTTPException(status_code=409, detail=f"Cannot request clarification in status '{app.status.value}'")
    if not transition_allowed(db, app.status, ApplicationStatus.DEFICIENCY_FOUND, current_user.role):
        raise HTTPException(status_code=409, detail="Clarification is not enabled from the current workflow stage")
    notice = notification_service.issue_clarification(db, app, current_user, body.notes, body.due_days, body.finding_ids)
    old = app.status
    app.status = ApplicationStatus.DEFICIENCY_FOUND
    app.decided_by, app.decided_at = current_user.id, datetime.now(timezone.utc)
    db.commit()
    audit_service.log_event(db=db, action="APPLICATION_DECISION", user_id=current_user.id, application_id=app.id,
                            details={"from": old.value, "to": app.status.value, "clarification_id": str(notice.id)})
    return notice
