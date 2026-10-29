"""Access control, authentication and upload safety."""

from app.core.security import hash_password, verify_password
from conftest import login


def _draft(client, headers, **kw):
    res = client.post("/api/applications", json={"category": "eoa", "permanent_id": "1-2345678901", "requested_intake": 360, **kw},
                      headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_health(client):
    assert client.get("/health").json()["status"] == "healthy"


def test_cors_allows_deployed_frontend_only(client):
    def preflight(origin):
        return client.options("/api/auth/login-json", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})

    ok = preflight("https://validex-two.vercel.app")
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "https://validex-two.vercel.app"
    assert preflight("https://evil.example.com").status_code == 400
    # The portal registers its encryption key with PUT
    put = client.options("/api/auth/public-key", headers={
        "Origin": "https://validex-two.vercel.app", "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "authorization,content-type"})
    assert put.status_code == 200


def test_self_registration_cannot_create_admin(client):
    res = client.post("/api/auth/register", json={"email": "evil@x.com", "password": "password123",
                                                   "full_name": "Evil", "role": "admin"})
    assert res.status_code == 201
    assert res.json()["role"] == "institution"


def test_password_hashes_are_salted():
    a, b = hash_password("same-password"), hash_password("same-password")
    assert a != b and verify_password("same-password", a) and not verify_password("wrong", a)
    assert not verify_password("plain", "plain")  # never falls back to plain-text comparison


def test_unauthenticated_requests_rejected(client):
    assert client.get("/api/applications").status_code == 401
    assert client.get("/api/dashboard/stats").status_code == 401


def test_bad_token_rejected(client):
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_institution_cannot_use_official_endpoints(client, apex):
    assert client.get("/api/dashboard/stats", headers=apex).status_code == 403
    assert client.get("/api/audit/system/recent", headers=apex).status_code == 403
    app = _draft(client, apex)
    res = client.post(f"/api/applications/{app['id']}/decision", json={"status": "approved"}, headers=apex)
    assert res.status_code == 403


def test_other_institution_cannot_reach_application_or_documents(client, apex, zenith, demo_sets):
    app = _draft(client, apex)
    _, name, data = demo_sets["apex"]["docs"][0]
    doc = client.post("/api/documents/upload", data={"application_id": app["id"], "doc_type": "fire_safety"},
                      files={"file": (name, data, "application/pdf")}, headers=apex).json()
    for url in (f"/api/applications/{app['id']}", f"/api/documents/{doc['id']}", f"/api/documents/{doc['id']}/file",
                f"/api/documents/{doc['id']}/page/0"):
        assert client.get(url, headers=zenith).status_code == 404, url
    for url in (f"/api/audit/{app['id']}", f"/api/validation/report/{app['id']}", f"/api/compliance/check/{app['id']}",
                f"/api/triage/{app['id']}"):
        assert client.get(url, headers=zenith).status_code == 403, url  # officer-only, even for the owner
    res = client.post("/api/documents/upload", data={"application_id": app["id"]},
                      files={"file": ("x.pdf", data, "application/pdf")}, headers=zenith)
    assert res.status_code == 404
    # The owner can still read everything
    assert client.get(f"/api/documents/{doc['id']}/file", headers=apex).status_code == 200


def test_institution_only_sees_notifications_sent_to_it(client, apex, officer):
    from datetime import datetime, timedelta, timezone

    application = _draft(client, apex)
    officer_id = client.get("/api/auth/me", headers=officer).json()["id"]
    deadline = client.post("/api/deadlines", headers=officer, json={
        "application_id": application["id"], "assigned_to": officer_id, "kind": "workflow",
        "title": "Officer-only reminder", "due_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "remind_before_hours": 2, "escalate_after_hours": 24,
    })
    assert deadline.status_code == 201, deadline.text
    assert client.post("/api/deadlines/process-due", headers=officer).status_code == 200

    institution_notices = client.get(f"/api/notifications?application_id={application['id']}", headers=apex)
    assert institution_notices.status_code == 200, institution_notices.text
    assert all("Officer-only reminder" not in item["subject"] for item in institution_notices.json())

    officer_notices = client.get(f"/api/notifications?application_id={application['id']}", headers=officer)
    assert any("Officer-only reminder" in item["subject"] for item in officer_notices.json())


def test_officials_do_not_see_drafts(client, apex, officer):
    app = _draft(client, apex)
    listed = {a["id"] for a in client.get("/api/applications", headers=officer).json()}
    assert app["id"] not in listed
    assert client.get(f"/api/applications/{app['id']}", headers=officer).status_code == 404


def test_upload_rejects_unsupported_and_spoofed_files(client, apex):
    app = _draft(client, apex)
    res = client.post("/api/documents/upload", data={"application_id": app["id"]},
                      files={"file": ("cert.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")}, headers=apex)
    assert res.status_code == 415
    res = client.post("/api/documents/upload", data={"application_id": app["id"]},
                      files={"file": ("empty.pdf", b"", "application/pdf")}, headers=apex)
    assert res.status_code == 400


def test_login_rate_limited(client):
    for _ in range(10):
        client.post("/api/auth/login-json", json={"email": "nobody@x.com", "password": "nope"})
    res = client.post("/api/auth/login-json", json={"email": "nobody@x.com", "password": "nope"})
    assert res.status_code == 429


def test_only_admin_creates_officials(client, officer, admin):
    body = {"email": "new.officer@aicte-india.org", "password": "password123", "full_name": "New", "role": "scrutiny"}
    assert client.post("/api/admin/users", json=body, headers=officer).status_code == 403
    assert client.post("/api/admin/users", json=body, headers=admin).status_code == 201
    login(client, "new.officer@aicte-india.org", "password123")
