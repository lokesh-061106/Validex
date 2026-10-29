"""Configurable workflow transitions; statutory decisions remain role-gated."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin, require_official
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.models.workflow_transition import WorkflowTransition
from app.schemas.workflow import WorkflowTransitionIn, WorkflowTransitionOut
from app.services.audit_service import audit_service

router = APIRouter(prefix="/workflow", tags=["Approval Workflow"])
ALLOWED_ROLES = {"institution", "scrutiny", "expert", "approver", "supervisor", "admin", "system"}


@router.get("/transitions", response_model=list[WorkflowTransitionOut])
def list_transitions(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(require_official)]):
    return db.query(WorkflowTransition).order_by(WorkflowTransition.from_status, WorkflowTransition.to_status).all()


@router.put("/transitions", response_model=WorkflowTransitionOut)
def configure_transition(data: WorkflowTransitionIn, db: Annotated[Session, Depends(get_db)],
                         user: Annotated[User, Depends(require_admin)]):
    if data.from_status == data.to_status:
        raise HTTPException(status_code=422, detail="A transition must change the application status")
    if not set(data.allowed_roles) <= ALLOWED_ROLES:
        raise HTTPException(status_code=422, detail=f"Roles must be selected from {sorted(ALLOWED_ROLES)}")
    row = db.query(WorkflowTransition).filter(
        WorkflowTransition.from_status == data.from_status.value,
        WorkflowTransition.to_status == data.to_status.value,
    ).first()
    before = {"allowed_roles": row.allowed_roles, "is_active": row.is_active} if row else None
    if row is None:
        row = WorkflowTransition(from_status=data.from_status.value, to_status=data.to_status.value,
                                 allowed_roles=data.allowed_roles, is_active=data.is_active)
        db.add(row)
    else:
        row.allowed_roles = data.allowed_roles
        row.is_active = data.is_active
    db.commit()
    db.refresh(row)
    audit_service.log_event(db=db, action="WORKFLOW_TRANSITION_CONFIGURED", user_id=user.id,
                            details={"from": row.from_status, "to": row.to_status, "before": before,
                                     "after": {"allowed_roles": row.allowed_roles, "is_active": row.is_active},
                                     "reason": data.change_reason})
    return row


@router.get("/history")
def workflow_history(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(require_official)]):
    logs = db.query(AuditLog).filter(AuditLog.action == "WORKFLOW_TRANSITION_CONFIGURED").order_by(AuditLog.created_at.desc()).limit(200).all()
    return [{"at": row.created_at, "actor_id": str(row.user_id) if row.user_id else None, "details": row.details} for row in logs]
