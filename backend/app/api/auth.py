"""Authentication: institution self-registration, login, profile."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import request_context
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.rate_limit import login_limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole
from app.schemas.auth import Token, UserCreate, UserLogin, UserResponse
from app.services.audit_service import audit_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Annotated[Session, Depends(get_db)]):
    """Self-registration creates an INSTITUTION account only. Official accounts are created by an admin."""
    email = user_in.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="A user with this email address already exists.")
    user = User(email=email, hashed_password=hash_password(user_in.password), full_name=user_in.full_name,
                role=UserRole.INSTITUTION, institution_name=user_in.institution_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    audit_service.log_event(db=db, action="USER_REGISTERED", user_id=user.id, actor_role="institution",
                            details={"email": user.email, "role": user.role.value})
    return user


def _login(db: Session, email: str, password: str) -> Token:
    email = email.lower().strip()
    key = f"{request_context.client_ip.get()}|{email}"
    if not login_limiter.allow(key):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a minute.")
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        audit_service.log_event(db=db, action="LOGIN_FAILED", details={"email": email})
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    token = create_access_token(data={"sub": str(user.id), "role": user.role.value})
    audit_service.log_event(db=db, action="USER_LOGIN", user_id=user.id, actor_role=user.role.value, details={"email": user.email})
    return Token(access_token=token, role=user.role.value, full_name=user.full_name, email=user.email)


@router.post("/login", response_model=Token)
def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: Annotated[Session, Depends(get_db)]):
    """OAuth2 password flow (used by Swagger 'Authorize')."""
    return _login(db, form_data.username, form_data.password)


@router.post("/login-json", response_model=Token)
def login_json(credentials: UserLogin, db: Annotated[Session, Depends(get_db)]):
    return _login(db, credentials.email, credentials.password)


class PublicKeyIn(BaseModel):
    public_key_pem: str


@router.put("/public-key")
def set_public_key(body: PublicKeyIn, db: Annotated[Session, Depends(get_db)],
                   current_user: Annotated[User, Depends(get_current_user)]):
    """Institution registers the public half of its browser-held key pair (secure clarification inbox)."""
    from app.services.secure_message import KeyError_, load_public_key
    if current_user.role != UserRole.INSTITUTION:
        raise HTTPException(status_code=403, detail="Only institutions hold an encrypted inbox")
    try:
        load_public_key(body.public_key_pem)
    except KeyError_ as e:
        raise HTTPException(status_code=422, detail=str(e))
    rotated = bool(current_user.public_key_pem) and current_user.public_key_pem != body.public_key_pem
    current_user.public_key_pem = body.public_key_pem
    db.commit()
    import hashlib
    audit_service.log_event(db=db, action="PUBLIC_KEY_ROTATED" if rotated else "PUBLIC_KEY_REGISTERED", user_id=current_user.id,
                            details={"fingerprint": hashlib.sha256(body.public_key_pem.encode()).hexdigest()[:16]})
    return {"registered": True, "rotated": rotated}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user
