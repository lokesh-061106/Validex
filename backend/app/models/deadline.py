"""Persistent workflow deadlines for EVCs, undertakings and expiring evidence."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import relationship

from app.core.database import Base


class DeadlineKind(str, enum.Enum):
    WORKFLOW = "workflow"
    EVC = "evc"
    UNDERTAKING = "undertaking"
    LEASE_EXPIRY = "lease_expiry"
    DOCUMENT_EXPIRY = "document_expiry"


class DeadlineStatus(str, enum.Enum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Deadline(Base):
    __tablename__ = "deadlines"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id = Column(Uuid, ForeignKey("applications.id"), nullable=False, index=True)
    created_by = Column(Uuid, ForeignKey("users.id"), nullable=False)
    assigned_to = Column(Uuid, ForeignKey("users.id"), nullable=True)
    kind = Column(Enum(DeadlineKind), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=False, index=True)
    remind_before_hours = Column(Integer, default=24, nullable=False)
    escalate_after_hours = Column(Integer, default=24, nullable=False)
    reminder_sent = Column(Boolean, default=False, nullable=False)
    escalation_level = Column(Integer, default=0, nullable=False)
    status = Column(Enum(DeadlineStatus), default=DeadlineStatus.OPEN, nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    application = relationship("Application")
