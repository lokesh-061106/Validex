import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.core.security import verify_password
from app.main import bootstrap_production_admin
from app.models.audit_log import AuditLog
from app.models.user import User, UserRole


@pytest.fixture
def empty_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_bootstrap_creates_and_audits_first_production_admin(empty_db, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "  owner@example.org  ")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "a-unique-password-with-32-chars")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_NAME", "Portal Owner")

    assert bootstrap_production_admin(empty_db) is True
    owner = empty_db.query(User).one()
    assert owner.email == "owner@example.org"
    assert owner.role == UserRole.ADMIN
    assert owner.full_name == "Portal Owner"
    assert verify_password("a-unique-password-with-32-chars", owner.hashed_password)
    assert empty_db.query(AuditLog).one().action == "INITIAL_ADMIN_BOOTSTRAPPED"
    assert bootstrap_production_admin(empty_db) is False
    assert empty_db.query(User).count() == 1


@pytest.mark.parametrize("email,password", [("owner@example.org", ""), ("", "a-unique-password-with-32-chars"),
                                             ("owner@example.org", "too-short")])
def test_bootstrap_rejects_incomplete_or_weak_credentials(empty_db, monkeypatch, email, password):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", email)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", password)
    with pytest.raises(RuntimeError):
        bootstrap_production_admin(empty_db)
    assert empty_db.query(User).count() == 0
