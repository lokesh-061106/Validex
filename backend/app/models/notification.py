"""Deficiency notices sent to institutions (the self-healing rectification loop)."""

import uuid
from datetime import datetime, timezone
import enum
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, JSON, Uuid
from sqlalchemy.orm import relationship

from app.core.database import Base


class NotificationStatus(str, enum.Enum):
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id = Column(Uuid, ForeignKey("applications.id"), nullable=False)
    recipient_id = Column(Uuid, ForeignKey("users.id"), nullable=False)
    sender_id = Column(Uuid, ForeignKey("users.id"), nullable=True)
    subject = Column(String(255), nullable=False)
    body = Column(String(4000), nullable=False)
    # Non-sensitive metadata only: [{fingerprint, rule_code, doc_type}] (content is in encrypted_payload)
    items = Column(JSON, default=list, nullable=False)
    # {alg, ek, iv, ct}: AES-256-GCM payload, key wrapped with the institution's RSA-OAEP public key
    encrypted_payload = Column(JSON, nullable=True)
    payload_sha256 = Column(String(64), nullable=True)
    channels = Column(JSON, default=list, nullable=False)  # ["in_app", "email"]
    status = Column(Enum(NotificationStatus), default=NotificationStatus.SENT, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)

    application = relationship("Application", back_populates="notifications")
