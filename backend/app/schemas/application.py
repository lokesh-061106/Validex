"""Pydantic schemas for AICTE applications."""

from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.models.application import AIRecommendation, ApplicationCategory, ApplicationStatus
from app.schemas.document import DocumentResponse
from app.schemas.validation import ValidationResultResponse


class ApplicationCreate(BaseModel):
    category: ApplicationCategory = ApplicationCategory.EOA
    academic_year: str = "2026-2027"
    permanent_id: str | None = Field(default=None, max_length=64)
    requested_intake: int | None = Field(default=None, ge=0, le=10000)


class ApplicationDecision(BaseModel):
    """An official's decision. Adverse decisions and overrides of the AI advice require reasons."""

    status: ApplicationStatus
    verdict_notes: str | None = Field(default=None, max_length=1000)


class ApplicationAssignmentUpdate(BaseModel):
    assigned_to: UUID | None
    reason: str = Field(min_length=5, max_length=1000)


class DeficiencyNoticeRequest(BaseModel):
    notes: str = Field(min_length=5, max_length=1000)
    due_days: int = Field(default=7, ge=1, le=60)
    finding_ids: list[UUID] | None = None


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_number: str
    institution_id: UUID
    institution_name: str
    permanent_id: str | None = None
    requested_intake: int | None = None
    category: ApplicationCategory
    academic_year: str
    status: ApplicationStatus
    risk_score: float
    ai_recommendation: AIRecommendation | None = None
    ai_summary: str | None = None
    ai_reviewed_at: datetime | None = None
    overall_verdict: str | None
    decided_at: datetime | None = None
    assigned_reviewer_id: UUID | None = None
    assigned_by: UUID | None = None
    assigned_at: datetime | None = None
    rectification_due: datetime | None = None
    submitted_at: datetime
    updated_at: datetime


class ApplicationDetailResponse(ApplicationResponse):
    documents: list[DocumentResponse] = []
    validation_results: list[ValidationResultResponse] = []
    checklist: list[dict] = []
    total_documents: int = 0
    pending_documents: int = 0
    flagged_documents: int = 0
