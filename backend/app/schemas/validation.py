"""Pydantic schemas for validation findings and the decision-support report."""

from uuid import UUID
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict
from app.models.validation_result import CheckType, Severity


class ValidationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_id: UUID
    document_id: UUID | None
    check_type: CheckType
    severity: Severity
    finding: str
    evidence: str | None
    fix_hint: str | None = None
    details: dict[str, Any]
    confidence: float
    rule_code: str | None = None
    rule_version: int | None = None
    rag: str | None = None
    actionable_by: str | None = None
    fingerprint: str | None = None
    created_at: datetime


class ValidationSummary(BaseModel):
    critical_flags: int
    warning_flags: int
    info_flags: int
    risk_score: float
    ai_recommendation: str | None
    ai_summary: str | None
    risk_contributions: list[dict[str, Any]]


class ValidationReportResponse(BaseModel):
    application_id: UUID
    application_number: str
    institution_name: str
    risk_score: float
    summary: ValidationSummary
    findings: list[ValidationResultResponse]
    generated_at: datetime
    disclaimer: str
