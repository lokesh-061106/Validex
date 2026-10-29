"""Deficiency notices: institutions read and acknowledge; officials see what was sent."""

import uuid
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_application_for_user, get_current_user
from app.models.notification import Notification, NotificationStatus
from app.models.user import User
from app.schemas.notification import NotificationResponse
from app.services.audit_service import audit_service

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationResponse])
def list_notifications(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(get_current_user)],
                       application_id: uuid.UUID | None = None):
    q = db.query(Notification)
    if application_id:
        app = get_application_for_user(db, application_id, current_user)
        q = q.filter(Notification.application_id == app.id)
    # Application ownership permits reading the institution's messages, not other
    # recipients' officer or scheduler notifications attached to that application.
    q = q.filter(Notification.recipient_id == current_user.id)
    return q.order_by(Notification.created_at.desc()).limit(100).all()


@router.post("/{notification_id}/acknowledge", response_model=NotificationResponse)
def acknowledge(notification_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                current_user: Annotated[User, Depends(get_current_user)]):
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if not n or n.recipient_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.status == NotificationStatus.SENT:
        n.status = NotificationStatus.ACKNOWLEDGED
        n.acknowledged_at = datetime.now(timezone.utc)
        db.commit()
        audit_service.log_event(db=db, action="NOTICE_ACKNOWLEDGED", user_id=current_user.id,
                                application_id=n.application_id, details={"notification_id": str(n.id)})
    return n
