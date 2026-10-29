"""SQLAlchemy Verification model for issuing-authority checks (API, QR code, digital signature)."""

import uuid
from datetime import datetime, timezone
import enum
from sqlalchemy import Column, String, Integer, DateTime, Enum, ForeignKey, JSON, Uuid
from sqlalchemy.orm import relationship

from app.core.database import Base


class VerificationMethod(str, enum.Enum):
    API = "api"
    QR_CODE = "qr_code"
    DIGITAL_SIGNATURE = "digital_signature"
    PORTAL = "portal"
    MANUAL = "manual"


class VerificationStatus(str, enum.Enum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    EXPIRED = "expired"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"
    MANUAL_REVIEW = "manual_review"


class Verification(Base):
    __tablename__ = "verifications"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id = Column(Uuid, ForeignKey("documents.id"), nullable=False)
    method = Column(Enum(VerificationMethod), default=VerificationMethod.API, nullable=False)
    source_authority = Column(String(255), nullable=False)  # e.g., "State Fire Services", "ICAI UDIN"
    status = Column(Enum(VerificationStatus), default=VerificationStatus.PENDING, nullable=False)
    # Minimal identifiers sent to the source (data minimisation) and the raw source response
    request_identifiers = Column(JSON, default=dict, nullable=True)
    source_response = Column(JSON, default=dict, nullable=False)
    # Field-by-field comparison of submitted vs. authority values
    field_comparison = Column(JSON, default=list, nullable=True)
    reason = Column(String(1000), nullable=True)
    attempts = Column(Integer, default=1, nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="verifications")
