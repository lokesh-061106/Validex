"""Persistent application deadlines, EVC events and expiry/undertaking tracking."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_application_for_user, get_current_user, require_official
from app.models.deadline import Deadline, DeadlineStatus
from app.models.user import User, UserRole
from app.schemas.deadline import DeadlineCreate, DeadlineResponse, DeadlineStatusUpdate
from app.services.audit_service import audit_service
from app.services.deadline_service import process_due_deadlines

router = APIRouter(prefix="/deadlines", tags=["Deadlines and EVC"])


@router.get("", response_model=list[DeadlineResponse])
def list_deadlines(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)],
                   status: DeadlineStatus | None = None, kind: str | None = None,
                   skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    q = db.query(Deadline).join(Deadline.application)
    if user.role == UserRole.INSTITUTION:
        q = q.filter(Deadline.application.has(institution_id=user.id))
    if status:
        q = q.filter(Deadline.status == status)
    if kind:
        q = q.filter(Deadline.kind == kind)
    return q.order_by(Deadline.due_at.asc()).offset(skip).limit(limit).all()


@router.post("", response_model=DeadlineResponse, status_code=201)
def create_deadline(data: DeadlineCreate, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    app = get_application_for_user(db, data.application_id, user)
    if user.role == UserRole.INSTITUTION and data.kind not in ("undertaking", "lease_expiry", "document_expiry"):
        raise HTTPException(status_code=403, detail="Institutions can register only their undertaking and expiry dates")
    if data.assigned_to:
        if user.role == UserRole.INSTITUTION:
            raise HTTPException(status_code=403, detail="Institution users cannot assign workflow tasks")
        assignee = db.query(User).filter(User.id == data.assigned_to, User.is_active.is_(True)).first()
        if not assignee or assignee.role == UserRole.INSTITUTION:
            raise HTTPException(status_code=422, detail="Assigned user must be an active official")
    due = data.due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    d = Deadline(**data.model_dump(exclude={"due_at"}), due_at=due, created_by=user.id)
    db.add(d)
    db.commit()
    db.refresh(d)
    audit_service.log_event(db=db, action="DEADLINE_CREATED", user_id=user.id, application_id=app.id,
                            details={"deadline_id": str(d.id), "kind": d.kind.value, "due_at": due.isoformat()})
    return d


@router.patch("/{deadline_id}", response_model=DeadlineResponse)
def update_deadline(deadline_id: UUID, data: DeadlineStatusUpdate, db: Annotated[Session, Depends(get_db)],
                    user: Annotated[User, Depends(get_current_user)]):
    d = db.query(Deadline).filter(Deadline.id == deadline_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Deadline not found")
    if user.role == UserRole.INSTITUTION and d.application.institution_id != user.id:
        raise HTTPException(status_code=404, detail="Deadline not found")
    if user.role == UserRole.INSTITUTION and data.status == DeadlineStatus.CANCELLED:
        raise HTTPException(status_code=403, detail="Institutions cannot cancel deadlines")
    d.status = data.status
    d.completed_at = datetime.now(timezone.utc) if data.status == DeadlineStatus.COMPLETED else None
    db.commit()
    audit_service.log_event(db=db, action="DEADLINE_STATUS_CHANGED", user_id=user.id,
                            application_id=d.application_id,
                            details={"deadline_id": str(d.id), "status": d.status.value, "reason": data.reason})
    return d


@router.post("/process-due")
def run_deadline_scheduler(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(require_official)]):
    """Run the same idempotent sweep configured for Celery beat; useful for local demos/ops."""
    return process_due_deadlines(db)
