"""Administrator-configurable allowed application-state transitions."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, JSON, String, Uuid, UniqueConstraint

from app.core.database import Base


class WorkflowTransition(Base):
    __tablename__ = "workflow_transitions"
    __table_args__ = (UniqueConstraint("from_status", "to_status", name="uq_workflow_transition_edge"),)

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    from_status = Column(String(32), nullable=False, index=True)
    to_status = Column(String(32), nullable=False, index=True)
    allowed_roles = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)
