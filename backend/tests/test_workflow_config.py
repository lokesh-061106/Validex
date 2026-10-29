def test_workflow_edges_are_admin_configured_and_enforced(client, admin, apex):
    edges = client.get("/api/workflow/transitions", headers=admin)
    assert edges.status_code == 200
    assert any(e["from_status"] == "draft" and e["to_status"] == "submitted" for e in edges.json())
    assert client.get("/api/workflow/transitions", headers=apex).status_code == 403

    app = client.post("/api/applications", json={"category": "eoa"}, headers=apex).json()
    saved = client.put("/api/workflow/transitions", headers=admin, json={
        "from_status": "draft", "to_status": "submitted", "allowed_roles": ["institution"],
        "is_active": False, "change_reason": "Temporarily freeze submissions for review",
    })
    assert saved.status_code == 200, saved.text
    submit = client.post(f"/api/applications/{app['id']}/submit", headers=apex)
    assert submit.status_code == 409
    assert "transition is not enabled" in submit.json()["detail"]

    restored = client.put("/api/workflow/transitions", headers=admin, json={
        "from_status": "draft", "to_status": "submitted", "allowed_roles": ["institution"],
        "is_active": True, "change_reason": "Reopen submissions after review",
    })
    assert restored.status_code == 200


def test_application_report_is_official_only_and_csv(client, admin, apex):
    assert client.get("/api/dashboard/report.csv", headers=apex).status_code == 403
    response = client.get("/api/dashboard/report.csv", headers=admin)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "application_number,institution,permanent_id" in response.text
