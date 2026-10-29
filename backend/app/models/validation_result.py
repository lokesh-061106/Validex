"""SQLAlchemy ValidationResult model for OCR, Forgery, and Compliance checks."""

import uuid
from datetime import datetime, timezone
import enum
from sqlalchemy import Column, String, Float, Integer, DateTime, Enum, ForeignKey, JSON, Uuid
from sqlalchemy.orm import relationship

from app.core.database import Base


class CheckType(str, enum.Enum):
    COMPLETENESS = "completeness"
    EXPIRY = "expiry"
    CONSISTENCY = "consistency"
    FORGERY = "forgery"
    COMPLIANCE = "compliance"
    INFRASTRUCTURE = "infrastructure"
    DUPLICATE = "duplicate"
    VERIFICATION = "verification"
    RECORDS = "records"


class Severity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ValidationResult(Base):
    """One evidence-linked finding. Findings are advisory indicators, never verdicts."""

    __tablename__ = "validation_results"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id = Column(Uuid, ForeignKey("applications.id"), nullable=False)
    document_id = Column(Uuid, ForeignKey("documents.id"), nullable=True)
    check_type = Column(Enum(CheckType), nullable=False)
    severity = Column(Enum(Severity), default=Severity.INFO, nullable=False)
    finding = Column(String(500), nullable=False)
    evidence = Column(String(2000), nullable=True)
    # Plain-language instruction shown to the institution on how to rectify
    fix_hint = Column(String(1000), nullable=True)
    details = Column(JSON, default=dict, nullable=False)
    confidence = Column(Float, default=1.0, nullable=False)
    rule_code = Column(String(64), nullable=True)
    rule_version = Column(Integer, nullable=True)
    # Triage: green (auto-pass) / amber (clarification) / red (officer must confirm or override)
    rag = Column(String(8), nullable=True, index=True)
    actionable_by = Column(String(16), nullable=True)  # institution | officer | system
    # Stable key so an officer's review survives re-screening while the finding is unchanged
    fingerprint = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    application = relationship("Application", back_populates="validation_results")
    document = relationship("Document", back_populates="validation_results")
