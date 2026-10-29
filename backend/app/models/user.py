"""SQLAlchemy User model with RBAC roles."""

import uuid
from datetime import datetime, timezone
import enum
from sqlalchemy import Column, String, Boolean, DateTime, Enum, Uuid
from sqlalchemy.orm import relationship

from app.core.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    SCRUTINY = "scrutiny"
    EXPERT = "expert"
    APPROVER = "approver"
    SUPERVISOR = "supervisor"
    INSTITUTION = "institution"


class User(Base):
    __tablename__ = "users"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.INSTITUTION, nullable=False)
    institution_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    # Institution's RSA-OAEP public key (SPKI PEM) for encrypted clarification requests;
    # the private key never leaves the institution's browser
    public_key_pem = Column(String(1200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    applications = relationship(
        "Application",
        back_populates="institution",
        cascade="all, delete-orphan",
        foreign_keys="Application.institution_id",
    )
    audit_logs = relationship("AuditLog", back_populates="user")
