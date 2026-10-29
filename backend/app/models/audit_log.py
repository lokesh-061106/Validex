"""Append-only, hash-chained audit ledger for automated checks and official actions."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Uuid
from sqlalchemy.orm import relationship

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True)
    actor_role = Column(String(32), nullable=True)  # "system" for automated checks
    # Plain reference, deliberately without a foreign key: a cascading SET NULL/DELETE would
    # rewrite ledger rows and break the hash chain. Entries keep the ID after an application is deleted.
    application_id = Column(Uuid, nullable=True, index=True)
    action = Column(String(128), nullable=False)  # e.g., "DOCUMENT_UPLOADED", "APPLICATION_DECISION"
    details = Column(JSON, default=dict, nullable=False)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    # Tamper evidence: each entry stores the hash of the previous entry
    prev_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=True, index=True)

    user = relationship("User", back_populates="audit_logs")
    application = relationship(
        "Application", back_populates="audit_logs",
        primaryjoin="foreign(AuditLog.application_id) == Application.id", viewonly=True,
    )
