"""Test configuration: isolated SQLite file DB, local temp storage, inline processing."""

import os
import sys
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="validex_test_")
os.environ.update({
    # TEST_DATABASE_URL lets the suite run against Postgres (must be an empty database)
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP}/test.db"),
    "INLINE_PROCESSING": "true",
    "USE_MINIO": "false",
    "USE_CELERY": "false",
    "ENVIRONMENT": "test",
    "SECRET_KEY": "test-secret-key-for-unit-tests-only-0123456789",
})
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.rate_limit import login_limiter  # noqa: E402
from app.core.storage import storage  # noqa: E402
from app.main import app  # noqa: E402
from app.mock_authority import service as mock_authority  # noqa: E402
from app.services.connectors import reset_breakers  # noqa: E402

storage.local_dir = os.path.join(_TMP, "vault")
os.makedirs(storage.local_dir, exist_ok=True)
storage.client = None


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_state():
    login_limiter.reset()
    mock_authority.set_outage(False)
    reset_breakers()
    yield
    mock_authority.set_outage(False)


def login(client, email: str, password: str) -> dict:
    res = client.post("/api/auth/login-json", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def admin(client):
    return login(client, "admin@aicte-india.org", "admin123")


@pytest.fixture
def officer(client):
    return login(client, "scrutiny@aicte-india.org", "scrutiny123")


@pytest.fixture
def approver(client):
    return login(client, "approver@aicte-india.org", "approver123")


@pytest.fixture
def supervisor(client):
    return login(client, "supervisor@aicte-india.org", "supervisor123")


@pytest.fixture
def apex(client):
    return login(client, "principal@apex.edu.in", "apex123")


@pytest.fixture
def zenith(client):
    return login(client, "principal@zenith.edu.in", "zenith123")


@pytest.fixture(scope="session")
def demo_sets():
    import demo_documents
    return demo_documents.build()
