"""Triage state for the officers' console: RAG grouping, red-finding reviews, approval gate."""

from typing import Any

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.finding_review import FindingReview, ReviewDecision
from app.models.validation_result import ValidationResult
from app.services.rule_engine import AMBER, GREEN, RED


def reviews_by_fingerprint(db: Session, app: Application) -> dict[str, FindingReview]:
    latest: dict[str, FindingReview] = {}
    for r in (db.query(FindingReview).filter(FindingReview.application_id == app.id)
              .order_by(FindingReview.created_at).all()):
        latest[r.fingerprint] = r
    return latest


def red_status(db: Session, app: Application) -> dict[str, Any]:
    reviews = reviews_by_fingerprint(db, app)
    reds = db.query(ValidationResult).filter(ValidationResult.application_id == app.id, ValidationResult.rag == RED).all()
    unreviewed = [f for f in reds if f.fingerprint not in reviews]
    confirmed = [f for f in reds if f.fingerprint in reviews and reviews[f.fingerprint].decision == ReviewDecision.CONFIRMED]
    overridden = [f for f in reds if f.fingerprint in reviews and reviews[f.fingerprint].decision == ReviewDecision.OVERRIDDEN]
    return {"total": len(reds), "unreviewed": unreviewed, "confirmed": confirmed, "overridden": overridden, "reviews": reviews}


def approval_blockers(db: Session, app: Application) -> list[str]:
    s = red_status(db, app)
    out = []
    if s["unreviewed"]:
        out.append(f"{len(s['unreviewed'])} red finding(s) still need officer confirmation or override")
    if s["confirmed"]:
        out.append(f"{len(s['confirmed'])} red finding(s) were confirmed as genuine anomalies")
    return out


def counts(db: Session, app: Application) -> dict[str, int]:
    rows = db.query(ValidationResult.rag, ValidationResult.actionable_by).filter(ValidationResult.application_id == app.id).all()
    s = red_status(db, app)
    return {
        "red": sum(1 for r, _ in rows if r == RED),
        "red_unreviewed": len(s["unreviewed"]),
        "amber": sum(1 for r, _ in rows if r == AMBER),
        "amber_institution": sum(1 for r, a in rows if r == AMBER and a == "institution"),
        "green_rules": 0,  # filled by callers that evaluate rules
    }


__all__ = ["reviews_by_fingerprint", "red_status", "approval_blockers", "counts", "GREEN", "AMBER", "RED"]
