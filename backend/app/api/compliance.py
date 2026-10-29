"""Configurable compliance rules (admin-editable, versioned, audited)."""

import uuid
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_application_for_user, get_current_user, require_admin, require_official
from app.models.application import ApplicationCategory
from app.models.audit_log import AuditLog
from app.models.compliance_rule import ComplianceRule
from app.models.document import DocumentType
from app.models.user import User
from app.schemas.compliance import (
    ComplianceEvaluationResponse, ComplianceRuleCreate, ComplianceRuleResponse, ComplianceRuleUpdate,
)
from app.services.audit_service import audit_service
from app.services.compliance_service import compliance_service
from app.services.rule_engine import OPS, RuleError, validate_expr

router = APIRouter(prefix="/compliance", tags=["Compliance Rules Engine"])

FACT_PREFIXES = ("app.", "docs.", "records.", "infra.", "computed.", "spatial.")
UNITS = {None, "acres", "hectares", "sqm", "sqft", "count", "ratio"}


def validate_conditions(conditions: dict[str, Any], applies_to: list[str] | None) -> None:
    """Reject malformed rules before they reach the engine."""
    req = conditions.get("requires_doc")
    if req is not None and req not in {d.value for d in DocumentType}:
        raise HTTPException(status_code=422, detail=f"Unknown document type '{req}'")
    check = conditions.get("check")
    if check is not None:
        if not isinstance(check, dict) or "op" not in check or not ("fact" in check or "expr" in check):
            raise HTTPException(status_code=422, detail="'check' must contain 'op' and a 'fact' or 'expr'")
        if "fact" in check and not str(check["fact"]).startswith(FACT_PREFIXES):
            raise HTTPException(status_code=422, detail=f"Fact must start with one of {FACT_PREFIXES}")
        if check["op"] not in OPS:
            raise HTTPException(status_code=422, detail=f"Operator must be one of {sorted(OPS)}")
        if check.get("unit") not in UNITS:
            raise HTTPException(status_code=422, detail=f"Unit must be one of {sorted(u for u in UNITS if u)}")
        value = check.get("value")
        try:
            if "expr" in check:
                validate_expr(check["expr"])
            if isinstance(value, dict) and "expr" in value:
                validate_expr(value["expr"])
        except (RuleError, SyntaxError) as e:
            raise HTTPException(status_code=422, detail=f"Invalid expression: {e}")
        if isinstance(value, dict) and "fact" in value and not str(value["fact"]).startswith(FACT_PREFIXES):
            raise HTTPException(status_code=422, detail="Fact reference in 'value' is invalid")
        if check["op"] == "between" and not (isinstance(value, list) and len(value) == 2):
            raise HTTPException(status_code=422, detail="'between' needs value [min, max]")
    if req is None and check is None:
        raise HTTPException(status_code=422, detail="A rule needs 'requires_doc' and/or 'check'")
    if conditions.get("on_missing_fact", "amber") not in ("amber", "red", "skip"):
        raise HTTPException(status_code=422, detail="on_missing_fact must be amber, red or skip")
    if conditions.get("fail_rag", "red") not in ("red", "amber"):
        raise HTTPException(status_code=422, detail="fail_rag must be red or amber")
    valid_categories = {c.value for c in ApplicationCategory}
    for cat in applies_to or []:
        if cat not in valid_categories:
            raise HTTPException(status_code=422, detail=f"Unknown application category '{cat}'")


@router.get("/rules", response_model=list[ComplianceRuleResponse])
def list_compliance_rules(db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(get_current_user)],
                          include_inactive: bool = False):
    q = db.query(ComplianceRule)
    if not include_inactive:
        q = q.filter(ComplianceRule.is_active.is_(True))
    return q.order_by(ComplianceRule.rule_code).all()


@router.post("/rules", response_model=ComplianceRuleResponse, status_code=status.HTTP_201_CREATED)
def create_compliance_rule(rule_in: ComplianceRuleCreate, current_user: Annotated[User, Depends(require_admin)],
                           db: Annotated[Session, Depends(get_db)]):
    if db.query(ComplianceRule).filter(ComplianceRule.rule_code == rule_in.rule_code).first():
        raise HTTPException(status_code=400, detail="Rule code already exists")
    validate_conditions(rule_in.conditions, rule_in.applies_to)
    rule = ComplianceRule(**rule_in.model_dump(), version=1)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    audit_service.log_event(db=db, action="RULE_CREATED", user_id=current_user.id,
                            details={"rule_code": rule.rule_code, "version": 1, "rule": rule_in.model_dump(mode="json")})
    return rule


@router.patch("/rules/{rule_id}", response_model=ComplianceRuleResponse)
def update_compliance_rule(rule_id: uuid.UUID, rule_in: ComplianceRuleUpdate,
                           current_user: Annotated[User, Depends(require_admin)], db: Annotated[Session, Depends(get_db)]):
    """Edit a rule (e.g. when the Approval Process Handbook changes). Bumps the version; the previous
    definition is kept in the audit ledger so past findings remain explainable."""
    rule = db.query(ComplianceRule).filter(ComplianceRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    changes = rule_in.model_dump(exclude_unset=True, exclude={"change_reason"})
    validate_conditions(changes.get("conditions", rule.conditions), changes.get("applies_to", rule.applies_to))
    before = ComplianceRuleResponse.model_validate(rule).model_dump(mode="json")
    for key, value in changes.items():
        setattr(rule, key, value)
    rule.version = (rule.version or 1) + 1
    db.commit()
    db.refresh(rule)
    audit_service.log_event(db=db, action="RULE_UPDATED", user_id=current_user.id,
                            details={"rule_code": rule.rule_code, "from_version": before["version"], "to_version": rule.version,
                                     "reason": rule_in.change_reason, "before": before,
                                     "changes": {k: (v.value if hasattr(v, "value") else v) for k, v in changes.items()}})
    return rule


@router.get("/rules/{rule_id}/history")
def rule_history(rule_id: uuid.UUID, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(get_current_user)]):
    rule = db.query(ComplianceRule).filter(ComplianceRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    logs = (db.query(AuditLog).filter(AuditLog.action.in_(["RULE_CREATED", "RULE_UPDATED"])).order_by(AuditLog.created_at.desc()).all())
    return [{"action": l.action, "at": l.created_at, "details": l.details} for l in logs
            if (l.details or {}).get("rule_code") == rule.rule_code]


@router.get("/check/{app_id}", response_model=ComplianceEvaluationResponse)
def evaluate_application_compliance(app_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                                    current_user: Annotated[User, Depends(require_official)]):
    app = get_application_for_user(db, app_id, current_user)
    return compliance_service.evaluate_compliance(db=db, application_id=app.id)


@router.get("/checklist/{app_id}")
def get_checklist(app_id: uuid.UUID, db: Annotated[Session, Depends(get_db)], current_user: Annotated[User, Depends(get_current_user)]):
    app = get_application_for_user(db, app_id, current_user)
    return compliance_service.checklist(db, app)
