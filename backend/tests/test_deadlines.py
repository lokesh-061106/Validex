from datetime import datetime, timedelta, timezone


def _new_application(client, institution):
    response = client.post("/api/applications", json={"category": "eoa", "requested_intake": 30}, headers=institution)
    assert response.status_code == 201, response.text
    return response.json()


def test_evc_deadline_is_persistent_and_due_sweep_is_idempotent(client, officer, apex):
    application = _new_application(client, apex)
    due = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    created = client.post("/api/deadlines", json={
        "application_id": application["id"], "kind": "evc", "title": "EVC visit",
        "description": "Synthetic demo visit", "due_at": due, "escalate_after_hours": 24,
    }, headers=officer)
    assert created.status_code == 201, created.text
    deadline_id = created.json()["id"]

    first = client.post("/api/deadlines/process-due", headers=officer)
    assert first.status_code == 200, first.text
    assert first.json()["reminders_created"] == 1
    assert first.json()["escalations_created"] == 1
    second = client.post("/api/deadlines/process-due", headers=officer)
    assert second.status_code == 200
    assert second.json() == {"reminders_created": 0, "escalations_created": 0}

    institution_view = client.get("/api/deadlines", headers=apex)
    assert institution_view.status_code == 200
    assert any(item["id"] == deadline_id and item["reminder_sent"] and item["escalation_level"] >= 1
               for item in institution_view.json())


def test_institution_cannot_schedule_officer_only_evc(client, apex):
    application = _new_application(client, apex)
    created = client.post("/api/deadlines", json={
        "application_id": application["id"], "kind": "evc", "title": "EVC visit",
        "due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }, headers=apex)
    assert created.status_code == 403


def test_signed_demo_qr_is_real_image_and_server_verified(client, admin):
    response = client.post("/api/verification/demo-qr", json={
        "issuer": "fire_services", "data": {"id": "DEMO-QR-001", "holder": "Synthetic Institute"},
    }, headers=admin)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["simulated"] is True
    assert result["verification"]["signature_valid"] is True
    assert result["qr_png_base64"].startswith("iVBOR")
