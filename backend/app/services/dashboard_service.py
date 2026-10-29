"""Dashboard analytics computed from live data (no placeholder numbers)."""

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.application import AIRecommendation, Application, ApplicationStatus
from app.models.audit_log import AuditLog
from app.models.document import Document, DocumentStatus
from app.models.user import User, UserRole
from app.models.validation_result import CheckType, Severity, ValidationResult
from app.models.verification import Verification, VerificationStatus
from app.schemas.dashboard import ActivityItem, AlertItem, DashboardStatsResponse, MetricsResponse, RiskDistributionItem

VISIBLE = Application.status != ApplicationStatus.DRAFT


class DashboardService:
    @staticmethod
    def _apps(db: Session, user: User | None = None) -> list[Application]:
        query = db.query(Application).filter(VISIBLE)
        if user and user.role in (UserRole.SCRUTINY, UserRole.EXPERT, UserRole.APPROVER):
            query = query.filter(or_(Application.assigned_reviewer_id.is_(None),
                                     Application.assigned_reviewer_id == user.id))
        return query.all()

    @staticmethod
    def get_stats(db: Session, user: User | None = None) -> DashboardStatsResponse:
        apps = DashboardService._apps(db, user)
        by_status = Counter(a.status for a in apps)
        app_ids = [a.id for a in apps]
        docs = db.query(Document).filter(Document.is_current.is_(True), Document.application_id.in_(app_ids)).all()
        times = [d.extracted_data.get("processing_seconds") for d in docs if (d.extracted_data or {}).get("processing_seconds")]
        now = datetime.now(timezone.utc)
        overdue = sum(1 for a in apps if a.status == ApplicationStatus.DEFICIENCY_FOUND and a.rectification_due
                      and (a.rectification_due if a.rectification_due.tzinfo else a.rectification_due.replace(tzinfo=timezone.utc)) < now)
        return DashboardStatsResponse(
            total_applications=len(apps),
            awaiting_review=by_status[ApplicationStatus.SUBMITTED] + by_status[ApplicationStatus.UNDER_REVIEW],
            deficiency_found=by_status[ApplicationStatus.DEFICIENCY_FOUND],
            approved=by_status[ApplicationStatus.APPROVED],
            rejected=by_status[ApplicationStatus.REJECTED],
            high_risk_flagged=sum(1 for a in apps if a.risk_score >= 60),
            total_documents_processed=sum(1 for d in docs if d.status not in (DocumentStatus.PENDING, DocumentStatus.PROCESSING)),
            tamper_suspected_count=sum(1 for d in docs if ((d.extracted_data or {}).get("forensics") or {}).get("is_suspected")),
            duplicate_flags=sum(1 for d in docs if (d.extracted_data or {}).get("duplicates")),
            pending_source_verifications=db.query(Verification).filter(
                Verification.status.in_([VerificationStatus.PENDING, VerificationStatus.UNAVAILABLE])).count(),
            avg_processing_seconds_per_document=round(sum(times) / len(times), 2) if times else None,
            overdue_rectifications=overdue,
        )

    @staticmethod
    def get_risk_distribution(db: Session, user: User | None = None) -> list[RiskDistributionItem]:
        scores = [a.risk_score for a in DashboardService._apps(db, user)]
        bands = [("Low (<25)", 0, 25, "#10B981"), ("Medium (25-59)", 25, 60, "#F59E0B"),
                 ("High (60-79)", 60, 80, "#F97316"), ("Critical (80+)", 80, 101, "#EF4444")]
        return [RiskDistributionItem(category=name, count=sum(1 for s in scores if lo <= s < hi), color=color)
                for name, lo, hi, color in bands]

    @staticmethod
    def get_alerts(db: Session, limit: int = 10, user: User | None = None) -> list[AlertItem]:
        app_ids = [a.id for a in DashboardService._apps(db, user)]
        rows = (
            db.query(ValidationResult, Application)
            .join(Application, ValidationResult.application_id == Application.id)
            .filter(VISIBLE, Application.id.in_(app_ids), ValidationResult.severity.in_([Severity.CRITICAL, Severity.WARNING]))
            .order_by(ValidationResult.created_at.desc())
            .limit(200).all()
        )
        rows.sort(key=lambda r: (r[0].severity != Severity.CRITICAL, -r[0].created_at.timestamp()))
        return [AlertItem(id=str(v.id), application_id=str(a.id), application_number=a.application_number,
                          institution_name=a.institution_name, title=v.finding, severity=v.severity.value,
                          check_type=v.check_type.value, message=v.evidence or "", created_at=v.created_at)
                for v, a in rows[:limit]]

    @staticmethod
    def get_recent_activity(db: Session, limit: int = 15, user: User | None = None) -> list[ActivityItem]:
        app_ids = [a.id for a in DashboardService._apps(db, user)]
        logs = (db.query(AuditLog, Application).outerjoin(Application, AuditLog.application_id == Application.id)
                .filter(AuditLog.action.notin_(["USER_LOGIN", "LOGIN_FAILED", "DOCUMENT_VIEWED"]))
                .filter(or_(AuditLog.application_id.is_(None), AuditLog.application_id.in_(app_ids)))
                .order_by(AuditLog.created_at.desc()).limit(limit).all())
        users = {u.id: u for u in db.query(User).filter(User.id.in_({l.user_id for l, _ in logs if l.user_id})).all()}
        out = []
        for log, app in logs:
            d = log.details or {}
            summary = d.get("filename") or d.get("to") or d.get("recommendation") or d.get("status") or d.get("rule_code") or ""
            out.append(ActivityItem(
                id=str(log.id), action=log.action.replace("_", " ").title(),
                user_name=users[log.user_id].full_name if log.user_id in users else "Automated check",
                institution_name=app.institution_name if app else "System", timestamp=log.created_at, details=str(summary)))
        return out

    @staticmethod
    def get_metrics(db: Session, user: User | None = None) -> MetricsResponse:
        """Operational metrics aligned with the problem statement's evaluation criteria."""
        apps = DashboardService._apps(db, user)
        app_ids = [a.id for a in apps]
        docs = db.query(Document).filter(Document.is_current.is_(True), Document.application_id.in_(app_ids)).all()
        doc_ids = [d.id for d in docs]
        verifs = db.query(Verification).filter(Verification.document_id.in_(doc_ids)).all()
        vc = Counter(v.status.value for v in verifs)
        completed = sum(vc[s] for s in ("verified", "mismatch", "expired"))
        levels = Counter(((d.extracted_data or {}).get("forensics") or {}).get("level", "not_run") for d in docs)
        times = [d.extracted_data.get("processing_seconds") for d in docs if (d.extracted_data or {}).get("processing_seconds")]
        decided = [a for a in apps if a.decided_at is not None]
        agree = 0
        for a in decided:
            ai_adverse = a.ai_recommendation in (AIRecommendation.DEFICIENCY, AIRecommendation.INSPECTION)
            human_adverse = a.status in (ApplicationStatus.DEFICIENCY_FOUND, ApplicationStatus.REJECTED)
            agree += int(ai_adverse == human_adverse)
        return MetricsResponse(
            verification={"total_checks": len(verifs), "by_status": dict(vc),
                           "automated_completion_rate": round(completed / len(verifs), 3) if verifs else None},
            forensics={"documents": len(docs), "by_level": dict(levels)},
            processing={"documents_with_timing": len(times),
                        "avg_seconds_per_document": round(sum(times) / len(times), 2) if times else None,
                        "max_seconds": max(times) if times else None},
            decisions={"decided": len(decided), "ai_human_agreement_rate": round(agree / len(decided), 3) if decided else None,
                       "duplicate_findings": db.query(ValidationResult).filter(ValidationResult.check_type == CheckType.DUPLICATE,
                                                                                ValidationResult.application_id.in_(app_ids)).count()},
        )


dashboard_service = DashboardService()
