"""Workflow policy lookup and safe default edge installation."""

from sqlalchemy.orm import Session

from app.models.application import ApplicationStatus
from app.models.user import UserRole
from app.models.workflow_transition import WorkflowTransition


DEFAULT_TRANSITIONS = [
    ("draft", "submitted", ["institution"]),
    ("deficiency_found", "submitted", ["institution"]),
    ("submitted", "under_review", ["system", "scrutiny", "supervisor"]),
    ("submitted", "deficiency_found", ["scrutiny", "expert"]),
    ("under_review", "deficiency_found", ["scrutiny", "expert"]),
    ("under_review", "verified", ["scrutiny"]),
    ("under_review", "approved", ["approver"]),
    ("under_review", "rejected", ["approver"]),
    ("deficiency_found", "verified", ["scrutiny"]),
    ("deficiency_found", "approved", ["approver"]),
    ("deficiency_found", "rejected", ["approver"]),
    ("verified", "approved", ["approver"]),
    ("verified", "rejected", ["approver"]),
]


def can_issue_final_decision(actor: UserRole | str) -> bool:
    """Only a separately provisioned approving officer can record statutory outcomes."""
    return actor == UserRole.APPROVER or actor == UserRole.APPROVER.value


def seed_default_transitions(db: Session) -> None:
    if db.query(WorkflowTransition).count():
        # Upgrade the original default decision edges without overwriting other
        # administrator-configured transitions in an existing database.
        for src, dst, roles in DEFAULT_TRANSITIONS:
            row = db.query(WorkflowTransition).filter_by(from_status=src, to_status=dst).first()
            if row is None:
                db.add(WorkflowTransition(from_status=src, to_status=dst, allowed_roles=roles, is_active=True))
            elif dst in ("approved", "rejected") and row.allowed_roles != ["approver"]:
                # The platform administrator and reviewers may not grant themselves
                # statutory decision authority through workflow configuration.
                row.allowed_roles = ["approver"]
        db.commit()
        return
    db.add_all([WorkflowTransition(from_status=src, to_status=dst, allowed_roles=roles, is_active=True)
                for src, dst, roles in DEFAULT_TRANSITIONS])
    db.commit()


def transition_allowed(db: Session, old: ApplicationStatus, new: ApplicationStatus, actor: UserRole | str) -> bool:
    edge = db.query(WorkflowTransition).filter(
        WorkflowTransition.from_status == old.value,
        WorkflowTransition.to_status == new.value,
        WorkflowTransition.is_active.is_(True),
    ).first()
    return bool(edge and actor in (edge.allowed_roles or []))
