"""Pydantic schemas for issuing-authority verification checks."""

from uuid import UUID
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict
from app.models.verification import VerificationMethod, VerificationStatus


class VerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    method: VerificationMethod
    source_authority: str
    status: VerificationStatus
    request_identifiers: dict[str, Any] | None = None
    source_response: dict[str, Any]
    field_comparison: list[dict[str, Any]] | None = None
    reason: str | None = None
    attempts: int | None = None
    next_retry_at: datetime | None = None
    verified_at: datetime
