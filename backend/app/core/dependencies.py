"""Common FastAPI dependencies for auth, RBAC and object-level access control."""

import uuid
from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core import request_context
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole
from app.models.application import Application
from app.models.document import Document

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

OFFICIAL_ROLES = [UserRole.ADMIN, UserRole.SCRUTINY, UserRole.EXPERT, UserRole.APPROVER, UserRole.SUPERVISOR]


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Validate bearer token and return the authenticated User."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    try:
        uid = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError):
        raise credentials_exception

    user = db.query(User).filter(User.id == uid).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user account")
    request_context.actor_role.set(user.role.value)
    return user


def require_role(allowed_roles: list[UserRole]):
    """Role-based access control dependency factory."""

    def role_checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Required roles: {[r.value for r in allowed_roles]}",
            )
        return current_user

    return role_checker


require_official = require_role(OFFICIAL_ROLES)
require_admin = require_role([UserRole.ADMIN])


def is_official(user: User) -> bool:
    return user.role in OFFICIAL_ROLES


def get_application_for_user(db: Session, app_id: uuid.UUID, user: User) -> Application:
    """Load an application, enforcing that institutions can only reach their own."""
    app = db.query(Application).filter(Application.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if not is_official(user) and app.institution_id != user.id:
        # 404 rather than 403 so other institutions' application IDs are not disclosed
        raise HTTPException(status_code=404, detail="Application not found")
    if (user.role in (UserRole.SCRUTINY, UserRole.EXPERT, UserRole.APPROVER)
            and app.assigned_reviewer_id is not None and app.assigned_reviewer_id != user.id):
        raise HTTPException(status_code=404, detail="Application not found")
    return app


def get_document_for_user(db: Session, doc_id: uuid.UUID, user: User) -> Document:
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    get_application_for_user(db, doc.application_id, user)
    return doc
