"""End-to-end: blind institution portal, private officer triage, red reviews, encrypted clarification."""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.secure_message import decrypt_with


def _submit_set(client, headers, spec, skip=()):
    app = client.post("/api/applications", json={"category": "eoa", "permanent_id": spec["permanent_id"],
                                                 "requested_intake": spec["intake"]}, headers=headers).json()
    for doc_type, name, data in spec["docs"]:
        if doc_type in skip:
            continue
        mime = "application/pdf" if name.endswith(".pdf") else "application/geo+json" if name.endswith(".geojson") else "image/jpeg"
        res = client.post("/api/documents/upload", data={"application_id": app["id"], "doc_type": doc_type},
                          files={"file": (name, data, mime)}, headers=headers)
        assert res.status_code == 201, res.text
        assert res.json()["state"] == "received" and set(res.json()) >= {"id", "state"}
        assert "extracted_data" not in res.json() and "status" not in res.json()  # blind: no analysis in the response
    res = client.post(f"/api/applications/{app['id']}/submit", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture(scope="module")
def crescent_app(client, demo_sets):
    from conftest import login
    return _submit_set(client, login(client, "principal@crescent.edu.in", "crescent123"), demo_sets["crescent"])


@pytest.fixture(scope="module")
def apex_app(client, demo_sets, crescent_app):
    from conftest import login
    return _submit_set(client, login(client, "principal@apex.edu.in", "apex123"), demo_sets["apex"])


@pytest.fixture(scope="module")
def zenith_app(client, demo_sets, apex_app):
    from conftest import login
    return _submit_set(client, login(client, "principal@zenith.edu.in", "zenith123"), demo_sets["zenith"])


def test_portal_is_blind_to_analysis(client, zenith_app, zenith):
    view = client.get(f"/api/applications/{zenith_app['id']}", headers=zenith).json()
    for leaked in ("risk_score", "ai_recommendation", "ai_summary", "validation_results"):
        assert leaked not in view
    assert all(set(d) <= {"id", "doc_type", "original_filename", "file_size", "uploaded_at", "is_current", "state"} for d in view["documents"])
    doc_id = view["documents"][0]["id"]
    for url in (f"/api/documents/{doc_id}/status", f"/api/documents/{doc_id}/evidence/evidence",
                f"/api/verification/status/{doc_id}", f"/api/documents/{doc_id}/custody"):
        assert client.get(url, headers=zenith).status_code == 403, url
    assert client.post(f"/api/validation/trigger/{zenith_app['id']}", headers=zenith).status_code == 403
    listed = client.get("/api/applications", headers=zenith).json()
    assert listed and "risk_score" not in listed[0]
    checklist = " ".join(c["description"] for c in view["checklist"]).lower()
    for method in ("cross-institution", "geodata", "provider", "forensic", "graph"):
        assert method not in checklist, method  # the checklist states norms, not detection methods


def test_clean_application_is_green_apart_from_lab_evidence(client, apex_app, officer):
    bundle = client.get(f"/api/triage/{apex_app['id']}", headers=officer).json()
    reds = [f for f in bundle["findings"] if f["rag"] == "red"]
    # Placeholder lab photos contain no equipment, so only the lab rule may be red
    assert all(f["rule_code"] == "COMP-LAB-08" for f in reds), [f["finding"] for f in reds]
    rules = {r["rule_code"]: r for r in bundle["rules"]}
    assert rules["COMP-FAC-03"]["rag"] == "green" and "ceil(" in rules["COMP-FAC-03"]["trace"][0]
    assert rules["COMP-GEO-13"]["rag"] == "green" and rules["COMP-GEO-14"]["rag"] == "green"
    assert all(d["watermark"].startswith("VALIDEX - CHAIN OF CUSTODY - VERIFIED") for d in bundle["documents"])


def test_problem_application_triage(client, zenith_app, officer):
    bundle = client.get(f"/api/triage/{zenith_app['id']}", headers=officer).json()
    red = " | ".join(f["finding"] for f in bundle["findings"] if f["rag"] == "red")
    amber = " | ".join(f["finding"] for f in bundle["findings"] if f["rag"] == "amber")
    assert "Possible alteration in fire_noc_renewed.pdf" in red
    assert "Same udin submitted by another institution" in red
    assert "is also declared by Apex" in red                       # shared faculty PAN (graph)
    assert "matches a different person" in red                     # biometric identity mismatch
    assert "Equipment serial CRS-DT-" in red                       # shifted equipment
    assert "lies outside the campus boundary" in red               # spatial
    assert "Footprint vs plan deviation" in red
    assert "stated 70 m² but 7 m × 9 m = 63 m²" in red              # blueprint dimensions
    assert "Regular faculty: 9 (required ≥ 60" in red              # deterministic 1:20 on 300 × 4 students
    assert "Required document not submitted: land document" in amber
    assert "expired" in amber.lower() and "TER payment status: unpaid" in amber
    assert "VXD" in red and "****" in red                          # PANs are masked
    graph = client.get(f"/api/triage/{zenith_app['id']}/graph", headers=officer).json()
    assert graph["backend"] in ("in-process", "neo4j") and len(graph["links"]) >= 6


def test_red_findings_gate_approval(client, apex_app, officer, approver):
    res = client.post(f"/api/applications/{apex_app['id']}/decision",
                      json={"status": "approved", "verdict_notes": "Lab verified during physical inspection"}, headers=officer)
    assert res.status_code == 403 and "approving officer" in res.json()["detail"]
    res = client.post(f"/api/applications/{apex_app['id']}/decision",
                      json={"status": "approved", "verdict_notes": "Lab verified during physical inspection"}, headers=approver)
    assert res.status_code == 409 and "red finding" in res.json()["detail"]
    bundle = client.get(f"/api/triage/{apex_app['id']}", headers=officer).json()
    amber = next((f for f in bundle["findings"] if f["rag"] != "red"), None)
    if amber:
        assert client.post(f"/api/triage/{apex_app['id']}/findings/{amber['id']}/review",
                           json={"decision": "overridden", "reason": "Not applicable here"}, headers=officer).status_code == 422
    for f in [f for f in bundle["findings"] if f["rag"] == "red"]:
        r = client.post(f"/api/triage/{apex_app['id']}/findings/{f['id']}/review",
                        json={"decision": "overridden", "reason": "Physically inspected: 60 workstations present"}, headers=officer)
        assert r.status_code == 200
    res = client.post(f"/api/applications/{apex_app['id']}/decision",
                      json={"status": "approved", "verdict_notes": "Lab verified during physical inspection"}, headers=approver)
    assert res.status_code == 200, res.text
    trail = client.get(f"/api/audit/{apex_app['id']}", headers=officer).json()
    assert any(e["action"] == "FINDING_REVIEWED" for e in trail) and any(e["action"] == "APPLICATION_DECISION" for e in trail)
    assert client.get("/api/audit/verify-chain", headers=officer).json()["valid"] is True


def test_encrypted_clarification_request(client, zenith_app, officer, zenith, demo_sets):
    # Without a registered key the request cannot be sent
    res = client.post(f"/api/applications/{zenith_app['id']}/clarification-request",
                      json={"notes": "Please supply the items below", "due_days": 7}, headers=officer)
    assert res.status_code == 409
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    assert client.put("/api/auth/public-key", json={"public_key_pem": pem}, headers=zenith).status_code == 200

    res = client.post(f"/api/applications/{zenith_app['id']}/clarification-request",
                      json={"notes": "Please supply the items below", "due_days": 7}, headers=officer)
    assert res.status_code == 201, res.text
    notice = client.get("/api/notifications", headers=zenith).json()[0]
    assert "encrypted" in notice["body"] and "Possible alteration" not in str(notice)
    payload = decrypt_with(private, notice["encrypted_payload"])
    text = str(payload).lower()
    assert "land document" in text and "expired" in text
    for secret in ("alteration", "forgery", "pan", "biometric", "duplicate", "serial", "footprint"):
        assert secret not in text, secret  # asymmetric: no forensic reasons reach the institution
    assert len({i["doc_type"] for i in payload["items"] if i["doc_type"]}) == len([i for i in payload["items"] if i["doc_type"]])

    view = client.get(f"/api/applications/{zenith_app['id']}", headers=zenith).json()
    assert view["status"] == "clarification_requested"
    noc = next(d for d in view["documents"] if d["doc_type"] == "noc" and d["is_current"])
    _, name, data = next(d for d in demo_sets["crescent"]["docs"] if d[0] == "noc")
    assert client.post(f"/api/documents/{noc['id']}/replace", files={"file": (name, data, "application/pdf")}, headers=zenith).status_code == 201
    assert client.post(f"/api/applications/{zenith_app['id']}/submit", headers=zenith).status_code == 200


def test_custody_and_tamper_detection(client, crescent_app, officer):
    from app.core.database import SessionLocal
    from app.core.storage import storage
    from app.models.document import Document
    from app.services.document_service import document_service

    bundle = client.get(f"/api/triage/{crescent_app['id']}", headers=officer).json()
    doc = next(d for d in bundle["documents"] if d["doc_type"] == "fire_safety")
    ok = client.get(f"/api/documents/{doc['id']}/custody", headers=officer).json()
    assert ok["intact"] is True and ok["checks"]["original_hash_matches"] and ok["checks"]["visible_watermark_present"]
    file = client.get(f"/api/documents/{doc['id']}/file", headers=officer).content
    assert b"CHAIN OF CUSTODY" in file or ok["checks"]["visible_watermark_present"]

    db = SessionLocal()
    try:
        d = db.get(Document, __import__("uuid").UUID(doc["id"]))
        stored = bytearray(storage.get_bytes(d.storage_path))
        stored[200] ^= 0xFF  # flip one byte inside the original revision
        storage.upload_bytes(bytes(stored), d.storage_path)
        bad = client.get(f"/api/documents/{doc['id']}/custody", headers=officer).json()
        assert bad["intact"] is False
        processed = document_service.process_document(db, d.id)
        assert processed.processing_stage == "custody_breach"
    finally:
        db.close()
