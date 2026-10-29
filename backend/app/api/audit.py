"""Audit ledger: per-application trail, system activity, tamper-evidence check."""

import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_application_for_user, require_official
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit_service import audit_service

router = APIRouter(prefix="/audit", tags=["Audit Trail & Governance"])


def _serialize(log: AuditLog, users: dict) -> dict:
    u = users.get(log.user_id)
    return {
        "id": str(log.id), "action": log.action, "details": log.details, "ip_address": log.ip_address,
        "created_at": log.created_at, "user_id": str(log.user_id) if log.user_id else None,
        "actor": u.full_name if u else "Automated check", "actor_role": log.actor_role,
        "application_id": str(log.application_id) if log.application_id else None,
        "entry_hash": log.entry_hash, "prev_hash": log.prev_hash,
    }


def _users(db: Session, logs: list[AuditLog]) -> dict:
    ids = {l.user_id for l in logs if l.user_id}
    return {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}


@router.get("/system/recent")
def get_system_audit_trail(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_official)],
                           limit: int = Query(100, ge=1, le=500), action: str | None = None):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    logs = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    users = _users(db, logs)
    return [_serialize(l, users) for l in logs]


@router.get("/verify-chain")
def verify_chain(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(require_official)]):
    """Recompute the hash chain to prove no audit entry was edited, deleted or inserted."""
    return audit_service.verify_chain(db)


@router.get("/{app_id}")
def get_application_audit_trail(app_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                                current_user: Annotated[User, Depends(require_official)]):
    app = get_application_for_user(db, app_id, current_user)
    logs = audit_service.get_application_logs(db=db, application_id=app.id)
    users = _users(db, logs)
    return [_serialize(l, users) for l in logs]
