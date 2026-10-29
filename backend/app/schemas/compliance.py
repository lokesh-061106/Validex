"""Pydantic schemas for compliance rules and evaluations."""

from uuid import UUID
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from app.models.compliance_rule import RuleCategory
from app.models.validation_result import Severity


class ComplianceRuleBase(BaseModel):
    rule_code: str = Field(min_length=3, max_length=64)
    title: str
    category: RuleCategory
    description: str
    conditions: dict[str, Any]
    applies_to: list[str] | None = []
    severity: Severity | None = Severity.CRITICAL
    handbook_reference: str | None = None
    is_active: bool = True


class ComplianceRuleCreate(ComplianceRuleBase):
    pass


class ComplianceRuleUpdate(BaseModel):
    title: str | None = None
    category: RuleCategory | None = None
    description: str | None = None
    conditions: dict[str, Any] | None = None
    applies_to: list[str] | None = None
    severity: Severity | None = None
    handbook_reference: str | None = None
    is_active: bool | None = None
    change_reason: str = Field(min_length=3, description="Why the rule changed (recorded in the audit ledger)")


class ComplianceRuleResponse(ComplianceRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class ComplianceCheckItem(BaseModel):
    rule_code: str
    title: str
    category: RuleCategory
    rag: str  # "green" | "amber" | "red" | "not_applicable"
    status: str  # legacy: "compliant" | "non_compliant" | "warning" | "not_applicable"
    message: str
    evidence: str | None = None
    rule_version: int | None = None
    expected: str | None = None
    actual: str | None = None
    fix_hint: str | None = None
    clause: str | None = None
    handbook_reference: str | None = None
    trace: list[str] = []


class ComplianceEvaluationResponse(BaseModel):
    application_id: UUID
    total_rules_evaluated: int
    compliant_count: int
    deficiency_count: int
    amber_count: int = 0
    compliance_score: float  # Percentage 0-100%
    results: list[ComplianceCheckItem]
