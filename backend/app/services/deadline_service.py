"""Idempotent deadline reminder and escalation processing."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.deadline import Deadline, DeadlineStatus
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.services.audit_service import audit_service


def _notify(db: Session, deadline: Deadline, recipient_id, subject: str, body: str, action: str) -> None:
    # The row lock plus the persisted reminder/escalation counters make repeated scheduler runs safe.
    db.add(Notification(application_id=deadline.application_id, recipient_id=recipient_id,
                        subject=subject[:255], body=body[:4000], items=[], channels=["in_app"]))
    audit_service.log_event(db=db, action=action, user_id=None, application_id=deadline.application_id,
                            details={"deadline_id": str(deadline.id), "kind": deadline.kind.value,
                                     "due_at": deadline.due_at.isoformat(), "level": deadline.escalation_level})


def process_due_deadlines(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    reminders = escalations = 0
    rows = db.query(Deadline).filter(Deadline.status == DeadlineStatus.OPEN).with_for_update().all()
    for d in rows:
        due = d.due_at if d.due_at.tzinfo else d.due_at.replace(tzinfo=timezone.utc)
        recipient = d.assigned_to or d.application.institution_id
        reminder_at = due - timedelta(hours=d.remind_before_hours)
        if not d.reminder_sent and now >= reminder_at:
            _notify(db, d, recipient, f"Upcoming deadline: {d.title}",
                    f"{d.title} for application {d.application.application_number} is due {due.isoformat()}.",
                    "DEADLINE_REMINDER")
            d.reminder_sent = True
            reminders += 1
        overdue_hours = (now - due).total_seconds() / 3600
        target_level = max(0, int(overdue_hours // d.escalate_after_hours)) if overdue_hours >= 0 else 0
        if target_level > d.escalation_level:
            d.escalation_level = target_level
            supervisors = db.query(User).filter(User.is_active.is_(True), User.role.in_(
                [UserRole.SUPERVISOR, UserRole.SCRUTINY, UserRole.ADMIN])).all()
            recipients = {recipient, *(u.id for u in supervisors)}
            for target in recipients:
                _notify(db, d, target, f"Overdue: {d.title}",
                        f"Deadline for application {d.application.application_number} is overdue. Escalation level {target_level}.",
                        "DEADLINE_ESCALATED")
            escalations += 1
    db.commit()
    return {"reminders_created": reminders, "escalations_created": escalations}
