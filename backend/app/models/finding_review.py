"""Officer decisions on RED findings (confirm the anomaly, or override it with a reason)."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Uuid

from app.core.database import Base


class ReviewDecision(str, enum.Enum):
    CONFIRMED = "confirmed"    # the anomaly is real
    OVERRIDDEN = "overridden"  # officer verified otherwise (e.g. original seen, inspection done)


class FindingReview(Base):
    __tablename__ = "finding_reviews"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id = Column(Uuid, ForeignKey("applications.id"), nullable=False, index=True)
    # Keyed by the finding fingerprint so the review survives re-screening while the finding is unchanged
    fingerprint = Column(String(64), nullable=False, index=True)
    finding_text = Column(String(500), nullable=False)
    decision = Column(Enum(ReviewDecision), nullable=False)
    reason = Column(String(1000), nullable=False)
    reviewer_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
