from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.deadline import DeadlineKind, DeadlineStatus


class DeadlineCreate(BaseModel):
    application_id: UUID
    assigned_to: UUID | None = None
    kind: DeadlineKind
    title: str = Field(min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    due_at: datetime
    remind_before_hours: int = Field(default=24, ge=0, le=8760)
    escalate_after_hours: int = Field(default=24, ge=1, le=8760)


class DeadlineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    application_id: UUID
    created_by: UUID
    assigned_to: UUID | None
    kind: DeadlineKind
    title: str
    description: str | None
    due_at: datetime
    remind_before_hours: int
    escalate_after_hours: int
    reminder_sent: bool
    escalation_level: int
    status: DeadlineStatus
    completed_at: datetime | None
    created_at: datetime


class DeadlineStatusUpdate(BaseModel):
    status: DeadlineStatus
    reason: str = Field(min_length=5, max_length=1000)
