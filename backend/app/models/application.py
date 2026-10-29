"""SQLAlchemy Application model."""

import uuid
from datetime import datetime, timezone
import enum
from sqlalchemy import Column, String, Float, Integer, DateTime, Enum, ForeignKey, Uuid
from sqlalchemy.orm import relationship

from app.core.database import Base


class ApplicationCategory(str, enum.Enum):
    EOA = "eoa"  # Extension of Approval
    NEW_INSTITUTION = "new_institution"
    CHANGE_INTAKE = "change_intake"
    CLOSURE = "closure"
    OTHER = "other"


class ApplicationStatus(str, enum.Enum):
    """Official workflow status. Only authorized officials move an application past UNDER_REVIEW."""

    DRAFT = "draft"  # institution is still preparing / self-checking; not visible in officials' queue
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    DEFICIENCY_FOUND = "deficiency_found"
    VERIFIED = "verified"
    APPROVED = "approved"
    REJECTED = "rejected"


class AIRecommendation(str, enum.Enum):
    """Advisory outcome of the automated pre-screening. Never applied automatically."""

    PENDING = "pending"
    FORWARD = "forward_for_approval"
    CLARIFICATION = "seek_clarification"
    DEFICIENCY = "deficiency_suspected"
    INSPECTION = "physical_inspection_suggested"


class Application(Base):
    __tablename__ = "applications"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    application_number = Column(String(64), unique=True, index=True, nullable=False)
    institution_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    institution_name = Column(String(255), nullable=False)
    # AICTE permanent institute ID used to look up institutional records
    permanent_id = Column(String(64), nullable=True, index=True)
    requested_intake = Column(Integer, nullable=True)
    category = Column(Enum(ApplicationCategory), default=ApplicationCategory.EOA, nullable=False)
    academic_year = Column(String(32), default="2026-2027", nullable=False)
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.SUBMITTED, nullable=False)

    # AI decision-support output (advisory only)
    risk_score = Column(Float, default=0.0, nullable=False)  # 0 to 100
    ai_recommendation = Column(Enum(AIRecommendation), default=AIRecommendation.PENDING, nullable=True)
    ai_summary = Column(String(1000), nullable=True)
    ai_reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # Official human decision
    overall_verdict = Column(String(1000), nullable=True)
    decided_by = Column(Uuid, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    rectification_due = Column(DateTime(timezone=True), nullable=True)
    assigned_reviewer_id = Column(Uuid, ForeignKey("users.id"), nullable=True, index=True)
    assigned_by = Column(Uuid, ForeignKey("users.id"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)

    submitted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    institution = relationship("User", back_populates="applications", foreign_keys=[institution_id])
    documents = relationship("Document", back_populates="application", cascade="all, delete-orphan")
    validation_results = relationship("ValidationResult", back_populates="application", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="application", cascade="all, delete-orphan")
    # Audit logs are intentionally NOT cascaded: the ledger must outlive the application.
    audit_logs = relationship(
        "AuditLog", back_populates="application", viewonly=True,
        primaryjoin="Application.id == foreign(AuditLog.application_id)",
    )
