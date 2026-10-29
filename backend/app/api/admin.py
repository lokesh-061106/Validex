"""Administration: official accounts, data retention, and simulated source controls."""

import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_admin
from app.core.security import hash_password
from app.mock_authority import service as mock_authority
from app.models.user import User
from app.schemas.auth import OfficialCreate, UserResponse
from app.services.audit_service import audit_service
from app.services.connectors import reset_breakers
from app.services.retention_service import purge_expired

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.get("/users", response_model=list[UserResponse])
def list_users(db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(require_admin)]):
    return db.query(User).order_by(User.created_at).all()


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(body: OfficialCreate, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(require_admin)]):
    email = body.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=email, hashed_password=hash_password(body.password), full_name=body.full_name,
                role=body.role, institution_name=body.institution_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    audit_service.log_event(db=db, action="USER_CREATED_BY_ADMIN", user_id=admin.id,
                            details={"new_user": str(user.id), "email": email, "role": body.role.value})
    return user


class ActiveToggle(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}", response_model=UserResponse)
def set_user_active(user_id: uuid.UUID, body: ActiveToggle, db: Annotated[Session, Depends(get_db)],
                    admin: Annotated[User, Depends(require_admin)]):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and not body.is_active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    user.is_active = body.is_active
    db.commit()
    audit_service.log_event(db=db, action="USER_ACTIVATION_CHANGED", user_id=admin.id,
                            details={"target": str(user.id), "is_active": body.is_active})
    return user


@router.post("/retention/purge")
def retention_purge(db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(require_admin)],
                    dry_run: bool = True, retention_days: int | None = None):
    """Delete stored files of decided applications older than the retention period (dry run by default)."""
    return purge_expired(db, admin.id, dry_run=dry_run, retention_days=retention_days)


class OutageToggle(BaseModel):
    enabled: bool


@router.post("/simulated-sources/outage")
def simulate_outage(body: OutageToggle, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(require_admin)]):
    """Test control: make the simulated issuing authorities unavailable to show retry handling."""
    if settings.AUTHORITY_API_URL:
        import httpx
        httpx.post(f"{settings.AUTHORITY_API_URL.rstrip('/')}/mock-authority/admin/outage", json={"enabled": body.enabled}, timeout=5)
    mock_authority.set_outage(body.enabled)
    reset_breakers()
    audit_service.log_event(db=db, action="SIMULATED_SOURCE_OUTAGE", user_id=admin.id, details={"enabled": body.enabled})
    return {"outage": body.enabled}


@router.get("/simulated-sources/status")
def simulated_status(admin: Annotated[User, Depends(require_admin)]):
    return {"outage": mock_authority.outage_enabled(), "mode": "http" if settings.AUTHORITY_API_URL else "in-process"}
