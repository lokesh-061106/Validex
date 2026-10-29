"""Officials' dashboard: KPIs, risk distribution, alerts, activity, evaluation metrics."""

from typing import Annotated
from datetime import date, datetime, time, timedelta, timezone
import csv
import io
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_official
from app.models.user import User, UserRole
from app.schemas.dashboard import ActivityItem, AlertItem, DashboardStatsResponse, MetricsResponse, RiskDistributionItem
from app.services.dashboard_service import dashboard_service
from app.models.application import Application, ApplicationStatus
from app.services.audit_service import audit_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard Analytics"])
Official = Annotated[User, Depends(require_official)]
DB = Annotated[Session, Depends(get_db)]


@router.get("/stats", response_model=DashboardStatsResponse)
def get_stats(db: DB, current_user: Official):
    return dashboard_service.get_stats(db, current_user)


@router.get("/risk-distribution", response_model=list[RiskDistributionItem])
def get_risk_distribution(db: DB, current_user: Official):
    return dashboard_service.get_risk_distribution(db, current_user)


@router.get("/alerts", response_model=list[AlertItem])
def get_alerts(db: DB, current_user: Official, limit: int = Query(10, ge=1, le=100)):
    return dashboard_service.get_alerts(db, limit=limit, user=current_user)


@router.get("/recent-activity", response_model=list[ActivityItem])
def get_recent_activity(db: DB, current_user: Official, limit: int = Query(15, ge=1, le=100)):
    return dashboard_service.get_recent_activity(db, limit=limit, user=current_user)


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(db: DB, current_user: Official):
    return dashboard_service.get_metrics(db, current_user)


@router.get("/report.csv")
def export_applications_report(
    db: DB, current_user: Official,
    date_from: date | None = None, date_to: date | None = None,
    status: ApplicationStatus | None = None,
    search: str | None = Query(None, max_length=100),
):
    """CSV report generated from persisted applications, with optional date/status/search filters."""
    q = db.query(Application).filter(Application.status != ApplicationStatus.DRAFT)
    if current_user.role in (UserRole.SCRUTINY, UserRole.EXPERT, UserRole.APPROVER):
        q = q.filter(or_(Application.assigned_reviewer_id.is_(None),
                         Application.assigned_reviewer_id == current_user.id))
    if date_from:
        q = q.filter(Application.submitted_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        q = q.filter(Application.submitted_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))
    if status:
        q = q.filter(Application.status == status)
    if search:
        like = f"%{search}%"
        q = q.filter(Application.institution_name.ilike(like) | Application.application_number.ilike(like))
    audit_service.log_event(db=db, action="APPLICATION_REPORT_EXPORTED", user_id=current_user.id,
                            details={"date_from": date_from.isoformat() if date_from else None,
                                     "date_to": date_to.isoformat() if date_to else None,
                                     "status": status.value if status else None,
                                     "search_used": bool(search)})
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["application_number", "institution", "permanent_id", "category", "academic_year",
                     "status", "risk_score", "ai_recommendation", "submitted_at", "decided_at", "verdict"])
    for a in q.order_by(Application.submitted_at.desc()).limit(10000):
        writer.writerow([a.application_number, a.institution_name, a.permanent_id or "", a.category.value,
                         a.academic_year, a.status.value, a.risk_score,
                         a.ai_recommendation.value if a.ai_recommendation else "", a.submitted_at.isoformat(),
                         a.decided_at.isoformat() if a.decided_at else "", a.overall_verdict or ""])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=validex-applications-report.csv"})
