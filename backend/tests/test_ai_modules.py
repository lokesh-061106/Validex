"""Forensics, QR verification, source statuses, duplicates, rule engine, audit chain."""

import synthetic as syn
from demo_documents import fire_noc

from app.ml.forgery_detector import forgery_detector
from app.ml.image_hash import hamming, phash
from app.ml.qr_verifier import verify_qr
from app.mock_authority import service as mock
from app.mock_authority.service import SourceUnavailable
from app.services.connectors import InProcessMockConnector
from app.services.matching import compare_field, name_similarity, ocr_fix_identifier

CERT = fire_noc("Test Institute of Technology", "DFS/HQ/2024/NOC-98421", "10/01/2024", "31/12/2027",
                "2024-01-10", "2027-12-31", "Greater Noida")


def test_clean_pdf_has_no_indicators():
    report = forgery_detector.analyze_document(CERT, "x.pdf")
    assert report.level == "none" and not report.indicators


def test_whiteout_edit_detected_with_hidden_value():
    report = forgery_detector.analyze_document(syn.tamper_whiteout(CERT, "31/12/2027", "31/12/2029"), "x.pdf")
    assert report.level == "high"
    cover = next(i for i in report.indicators if i["method"] == "Cover-up detection")
    assert cover["hidden_text"] == "31/12/2027" and cover["boxes"]


def test_redaction_with_new_font_detected():
    report = forgery_detector.analyze_document(syn.tamper_redact(CERT, "31/12/2027", "31/12/2029"), "x.pdf")
    assert report.is_tampered and any(i["method"] == "Font consistency" for i in report.indicators)


def test_metadata_edit_detected():
    report = forgery_detector.analyze_document(syn.tamper_metadata(CERT), "x.pdf")
    assert report.is_tampered


def test_clean_scans_not_flagged():
    page = syn.render(CERT)
    for seed in range(4):
        assert not forgery_detector.analyze_document(syn.scan(page, seed, noise=2 + seed), "s.jpg").is_tampered


def test_digital_paste_on_scan_detected():
    page = syn.render(CERT)
    pasted = syn.scan_paste(syn.scan(page, 7, noise=6, quality=90), (95, 300, 340, 330), "Valid Up to: 31/12/2030")
    assert forgery_detector.analyze_document(pasted, "s.jpg").is_tampered


def test_signed_qr_verifies_and_detects_alteration():
    good = verify_qr(CERT, True)
    assert good["signature_valid"] and good["data"]["valid_until"] == "2027-12-31"
    tampered = verify_qr(syn.tamper_whiteout(CERT, "31/12/2027", "31/12/2029"), True)
    assert compare_field("valid_until", "31/12/2029", tampered["data"]["valid_until"], "date")["match"] is False


def test_source_statuses():
    conn = InProcessMockConnector()
    assert conn.lookup("fire_services", "DFS/HQ/2024/NOC-98421")["status"] == "found"
    assert conn.lookup("fire_services", "DFS/HQ/1999/NOC-00000")["status"] == "not_found"
    assert conn.lookup("university_noc", "AKTU/NOC/2026/1290")["status"] == "pending"
    mock.set_outage(True)
    try:
        conn.lookup("fire_services", "DFS/HQ/2024/NOC-98421")
        assert False, "expected SourceUnavailable"
    except SourceUnavailable:
        pass


def test_near_duplicate_photos():
    a = syn.lab_placeholder(1, "A")
    assert hamming(phash(a), phash(syn.recompress_resize(a, 0.7, 70))) <= 8
    assert hamming(phash(a), phash(syn.lab_placeholder(2, "B"))) > 8


def test_fuzzy_names_and_ocr_identifier_repair():
    assert name_similarity("Apex Inst. of Tech. & Engg.", "Apex Institute of Technology and Engineering") >= 88
    assert name_similarity("Zenith College of Engineering", "Apex Institute of Technology") < 70
    assert ocr_fix_identifier("AKTU/NOC/2O26/1187") == "AKTU/NOC/2026/1187"
    assert ocr_fix_identifier("26054321BKAPEX1234") == "26054321BKAPEX1234"


def test_rule_edit_is_versioned_and_changes_outcome(client, admin, officer):
    rules = client.get("/api/compliance/rules", headers=admin).json()
    lab = next(r for r in rules if r["rule_code"] == "COMP-LAND-02")
    cond = {**lab["conditions"], "check": {**lab["conditions"]["check"], "value": 15}}
    res = client.patch(f"/api/compliance/rules/{lab['id']}", json={"conditions": cond, "change_reason": "Handbook revision"},
                       headers=admin)
    assert res.status_code == 200 and res.json()["version"] == lab["version"] + 1
    history = client.get(f"/api/compliance/rules/{lab['id']}/history", headers=officer).json()
    assert history[0]["details"]["reason"] == "Handbook revision"
    # revert
    client.patch(f"/api/compliance/rules/{lab['id']}", json={"conditions": lab["conditions"], "change_reason": "Revert"}, headers=admin)


def test_invalid_rule_rejected(client, admin, officer):
    bad = {"rule_code": "BAD-01", "title": "Bad", "category": "safety", "description": "x",
           "conditions": {"check": {"fact": "os.system", "op": ">="}}}
    assert client.post("/api/compliance/rules", json=bad, headers=admin).status_code == 422
    good = {**bad, "conditions": {"requires_doc": "noc"}}
    assert client.post("/api/compliance/rules", json=good, headers=officer).status_code == 403


def test_deleting_application_keeps_audit_chain_intact(client, officer, apex):
    from app.core.database import SessionLocal
    from app.models.application import Application
    from app.models.audit_log import AuditLog

    app_id = client.post("/api/applications", json={"category": "eoa"}, headers=apex).json()["id"]
    db = SessionLocal()
    try:
        app = db.get(Application, __import__("uuid").UUID(app_id))
        db.delete(app)
        db.commit()
        assert db.query(AuditLog).filter(AuditLog.application_id == app.id).count() >= 1  # ledger keeps the reference
    finally:
        db.close()
    assert client.get("/api/audit/verify-chain", headers=officer).json()["valid"] is True


def test_audit_chain_detects_tampering(client, officer):
    from app.core.database import SessionLocal
    from app.models.audit_log import AuditLog

    assert client.get("/api/audit/verify-chain", headers=officer).json()["valid"] is True
    db = SessionLocal()
    try:
        entry = db.query(AuditLog).filter(AuditLog.entry_hash.isnot(None)).order_by(AuditLog.created_at).first()
        original = dict(entry.details)
        entry.details = {**original, "tampered": True}
        db.commit()
        result = client.get("/api/audit/verify-chain", headers=officer).json()
        assert result["valid"] is False and result["problems"][0]["problem"] == "entry content was modified"
        entry.details = original
        db.commit()
    finally:
        db.close()
