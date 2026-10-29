"""AI pre-screening: trigger, evidence-linked report, raw findings."""

import uuid
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_application_for_user, require_official
from app.models.application import ApplicationStatus
from app.models.user import User
from app.models.validation_result import Severity, ValidationResult
from app.schemas.validation import ValidationReportResponse, ValidationResultResponse, ValidationSummary
from app.services.validation_service import SEVERITY_POINTS, validation_service

router = APIRouter(prefix="/validation", tags=["AI Pre-screening"])

SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
DISCLAIMER = ("AI-generated findings are decision-support only. Forgery indicators are preliminary and require human "
              "verification. Statutory scrutiny, inspection and final decisions rest with the competent AICTE authority.")


@router.post("/trigger/{app_id}")
def trigger_validation(app_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                       current_user: Annotated[User, Depends(require_official)]):
    """Officers only: screening results are never shown to institutions (blind portal)."""
    app = get_application_for_user(db, app_id, current_user)
    return {"message": "Pre-screening complete", "data": validation_service.validate_application(db, app.id, current_user.id)}


@router.get("/report/{app_id}", response_model=ValidationReportResponse)
def get_validation_report(app_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                          current_user: Annotated[User, Depends(require_official)]):
    app = get_application_for_user(db, app_id, current_user)
    findings = sorted(
        db.query(ValidationResult).filter(ValidationResult.application_id == app.id).all(),
        key=lambda f: (SEVERITY_ORDER[f.severity], f.check_type.value),
    )
    counts = {s: sum(1 for f in findings if f.severity == s) for s in Severity}
    summary = ValidationSummary(
        critical_flags=counts[Severity.CRITICAL], warning_flags=counts[Severity.WARNING], info_flags=counts[Severity.INFO],
        risk_score=app.risk_score,
        ai_recommendation=app.ai_recommendation.value if app.ai_recommendation else None,
        ai_summary=app.ai_summary,
        risk_contributions=[{"finding": f.finding, "severity": f.severity.value, "points": SEVERITY_POINTS[f.severity]}
                            for f in findings if SEVERITY_POINTS[f.severity] > 0],
    )
    return ValidationReportResponse(
        application_id=app.id, application_number=app.application_number, institution_name=app.institution_name,
        risk_score=app.risk_score, summary=summary,
        findings=[ValidationResultResponse.model_validate(f) for f in findings],
        generated_at=datetime.now(timezone.utc), disclaimer=DISCLAIMER,
    )


@router.get("/results/{app_id}", response_model=list[ValidationResultResponse])
def get_validation_results(app_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                           current_user: Annotated[User, Depends(require_official)]):
    app = get_application_for_user(db, app_id, current_user)
    return db.query(ValidationResult).filter(ValidationResult.application_id == app.id).all()
