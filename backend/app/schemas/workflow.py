from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.application import ApplicationStatus

class WorkflowTransitionIn(BaseModel):
    from_status: ApplicationStatus
    to_status: ApplicationStatus
    allowed_roles: list[str] = Field(min_length=1)
    is_active: bool = True
    change_reason: str = Field(min_length=5, max_length=1000)


class WorkflowTransitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    from_status: str
    to_status: str
    allowed_roles: list[str]
    is_active: bool
    updated_at: datetime
