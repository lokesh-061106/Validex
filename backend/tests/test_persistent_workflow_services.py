"""Service-level regression tests independent of the HTTPX TestClient runtime."""

import base64
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.api.notifications import list_notifications
from app.api.applications import ApplicationAssignmentUpdate, assign_application, list_applications, list_reviewers
from app.ml.qr_verifier import render_qr_png, verify_qr
from app.mock_authority.keys import sign_payload
from app.models.application import Application, ApplicationCategory, ApplicationStatus
from app.models.deadline import Deadline, DeadlineKind
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.models.workflow_transition import WorkflowTransition
from app.services.deadline_service import process_due_deadlines
from app.services.workflow_service import can_issue_final_decision, transition_allowed


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _records(db):
    institution = User(email="institution@unit.invalid", hashed_password="unused", full_name="Unit Institute",
                       role=UserRole.INSTITUTION, institution_name="Unit Institute")
    reviewer = User(email="reviewer@unit.invalid", hashed_password="unused", full_name="Unit Reviewer", role=UserRole.SCRUTINY)
    db.add_all([institution, reviewer]); db.flush()
    app = Application(application_number="UNIT-APP-1", institution_id=institution.id,
                      institution_name=institution.institution_name, category=ApplicationCategory.EOA,
                      academic_year="2026-2027", status=ApplicationStatus.UNDER_REVIEW)
    db.add(app); db.flush()
    return institution, reviewer, app


def test_deadline_reminders_escalate_and_repeat_safely(db):
    institution, reviewer, app = _records(db)
    due = datetime.now(timezone.utc) - timedelta(hours=25)
    deadline = Deadline(application_id=app.id, created_by=reviewer.id, assigned_to=reviewer.id,
                        kind=DeadlineKind.EVC, title="EVC review", due_at=due,
                        remind_before_hours=24, escalate_after_hours=24)
    db.add(deadline); db.commit()

    assert process_due_deadlines(db) == {"reminders_created": 1, "escalations_created": 1}
    first_count = db.query(Notification).count()
    assert first_count >= 2  # reviewer reminder plus overdue alerts to assigned officer and scrutiny/admin
    assert process_due_deadlines(db) == {"reminders_created": 0, "escalations_created": 0}
    assert db.query(Notification).count() == first_count


def test_workflow_role_edge_is_persisted_and_enforced(db):
    db.add(WorkflowTransition(from_status="draft", to_status="submitted", allowed_roles=["institution"], is_active=True))
    db.commit()
    assert transition_allowed(db, ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED, UserRole.INSTITUTION)
    assert not transition_allowed(db, ApplicationStatus.DRAFT, ApplicationStatus.SUBMITTED, UserRole.SCRUTINY)


def test_application_notifications_are_scoped_to_the_recipient(db):
    institution, reviewer, app = _records(db)
    db.add_all([
        Notification(application_id=app.id, recipient_id=institution.id, subject="Institution notice", body="own"),
        Notification(application_id=app.id, recipient_id=reviewer.id, subject="Officer reminder", body="private"),
    ])
    db.commit()

    institution_view = list_notifications(db, institution, app.id)
    officer_view = list_notifications(db, reviewer, app.id)
    assert [n.subject for n in institution_view] == ["Institution notice"]
    assert [n.subject for n in officer_view] == ["Officer reminder"]


def test_only_approver_can_issue_a_final_decision(db):
    assert can_issue_final_decision(UserRole.APPROVER)
    assert not can_issue_final_decision(UserRole.ADMIN)
    assert not can_issue_final_decision(UserRole.SCRUTINY)


def test_dashboard_and_application_access_follow_reviewer_assignment(db):
    from fastapi import HTTPException
    from app.core.dependencies import get_application_for_user
    from app.services.dashboard_service import dashboard_service

    institution, reviewer, app = _records(db)
    other = User(email="other@unit.invalid", hashed_password="unused", full_name="Other Reviewer", role=UserRole.EXPERT)
    db.add(other); db.flush()
    hidden = Application(application_number="UNIT-APP-2", institution_id=institution.id,
                         institution_name=institution.institution_name, category=ApplicationCategory.EOA,
                         academic_year="2026-2027", status=ApplicationStatus.UNDER_REVIEW,
                         assigned_reviewer_id=other.id)
    db.add(hidden); db.commit()
    assert get_application_for_user(db, app.id, reviewer) is app
    try:
        get_application_for_user(db, hidden.id, reviewer)
        assert False, "an assigned case must not be visible to another reviewer"
    except HTTPException as error:
        assert error.status_code == 404
    assert {row.application_number for row in dashboard_service._apps(db, reviewer)} == {app.application_number}


def test_supervisor_assignment_is_persisted_and_audited(db):
    from app.models.audit_log import AuditLog

    institution, reviewer, app = _records(db)
    supervisor = User(email="supervisor@unit.invalid", hashed_password="unused", full_name="Unit Supervisor",
                      role=UserRole.SUPERVISOR)
    approver = User(email="approver@unit.invalid", hashed_password="unused", full_name="Unit Approver",
                    role=UserRole.APPROVER)
    db.add_all([supervisor, approver]); db.commit()

    directory = list_reviewers(db, supervisor)
    assert {item["role"] for item in directory} == {"scrutiny", "approver"}
    updated = assign_application(app.id, ApplicationAssignmentUpdate(assigned_to=approver.id, reason="Route for final review"), db, supervisor)
    assert updated.assigned_reviewer_id == approver.id and updated.assigned_by == supervisor.id
    visible = list_applications(db, approver, status=None, category=None, search=None, skip=0, limit=50)
    assert any(row.id == app.id for row in visible)
    assert not any(row.id == app.id for row in list_applications(db, reviewer, status=None, category=None, search=None, skip=0, limit=50))
    event = db.query(AuditLog).filter_by(action="APPLICATION_ASSIGNED", application_id=app.id).one()
    assert event.details["assigned_to"] == str(approver.id) and event.details["reason"] == "Route for final review"


def test_signed_demo_qr_png_decodes_and_verifies_server_side():
    payload = {"id": "UNIT-QR-1", "holder": "Synthetic Institute"}
    qr_text = sign_payload("fire_services", payload)
    png = base64.b64decode(render_qr_png(qr_text))
    checked = verify_qr(png, is_pdf=False)
    assert checked is not None and checked["format_ok"] and checked["signature_valid"]
    assert checked["issuer"] == "fire_services" and checked["data"] == payload
