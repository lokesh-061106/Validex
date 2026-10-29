"""Verification against original issuing authorities: signed QR codes and authority lookups.

Statuses: verified | mismatch | expired | pending | unavailable | manual_review.
Every check records the source, the minimal identifiers sent, the raw response, a field-by-field
comparison, a reason and a timestamp.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import storage
from app.ml.dates import parse_date, today
from app.ml.qr_verifier import verify_qr
from app.mock_authority.service import SourceUnavailable, authority_name
from app.models.document import Document, DocumentType
from app.models.verification import Verification, VerificationMethod, VerificationStatus
from app.services.audit_service import audit_service
from app.services.connectors import backoff_delay, get_connector
from app.services.matching import compare_field

logger = logging.getLogger(__name__)

# doc type -> source, identifier field, and (extracted_field, official_field, kind) comparisons
SOURCES: dict[DocumentType, dict[str, Any]] = {
    DocumentType.FIRE_SAFETY: {
        "authority": "fire_services", "id_field": "certificate_number", "expiry": "valid_until",
        "compare": [("holder", "holder", "name"), ("valid_until", "valid_until", "date"), ("issue_date", "issue_date", "date")],
    },
    DocumentType.AUDIT_REPORT: {
        "authority": "icai_udin", "id_field": "udin",
        "compare": [("client_name", "client", "name"), ("financial_year", "financial_year", "text"),
                    ("ca_membership_no", "membership_no", "identifier")],
    },
    DocumentType.LAND_DOCUMENT: {
        "authority": "land_records", "id_field": "deed_number",
        "compare": [("owner", "owner", "name"), ("land_area_acres", "area_acres", "number")],
    },
    DocumentType.NOC: {
        "authority": "university_noc", "id_field": "noc_number", "expiry": "valid_until",
        "compare": [("holder", "institution", "name"), ("valid_until", "valid_until", "date")],
    },
    DocumentType.AFFIDAVIT: {
        "authority": "estamp", "id_field": "stamp_certificate_no",
        "compare": [("deponent_institution", "party", "name")],
    },
}
FINAL_STATUSES = {VerificationStatus.VERIFIED, VerificationStatus.MISMATCH, VerificationStatus.EXPIRED}


def _compare(spec: dict[str, Any], extracted: dict[str, Any], official: dict[str, Any]) -> list[dict[str, Any]]:
    return [compare_field(ext_key, extracted.get(ext_key), official.get(off_key), kind)
            for ext_key, off_key, kind in spec["compare"]]


def _outcome(rows: list[dict[str, Any]], official: dict[str, Any], spec: dict[str, Any]) -> tuple[VerificationStatus, str]:
    mismatched = [r for r in rows if r["match"] is False]
    if mismatched:
        parts = [f"{r['field']}: document shows '{r['submitted']}', source has '{r['official']}'" for r in mismatched]
        return VerificationStatus.MISMATCH, "Mismatch with issuing authority — " + "; ".join(parts)
    exp_key = spec.get("expiry")
    if exp_key:
        d = parse_date(str(official.get(exp_key, "")))
        if d and d < today():
            return VerificationStatus.EXPIRED, f"Authority record shows validity ended on {d.strftime('%d/%m/%Y')}"
    unknown = [r["field"] for r in rows if r["match"] is None]
    if unknown and len(unknown) == len(rows):
        return VerificationStatus.MANUAL_REVIEW, "Record found but no fields could be compared automatically"
    return VerificationStatus.VERIFIED, "All compared fields match the issuing authority's record" + (
        f" (not compared: {', '.join(unknown)})" if unknown else "")


class VerificationService:
    def supports(self, doc: Document) -> bool:
        return doc.doc_type in SOURCES

    def verify_document(self, db: Session, document_id: uuid.UUID, user_id: uuid.UUID | None = None,
                        file_bytes: bytes | None = None) -> list[Verification]:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            raise ValueError("Document not found")
        results: list[Verification] = []
        if file_bytes is None:
            from app.services.document_service import CustodyBreach, document_service
            try:
                file_bytes = document_service.original_bytes(doc)
            except (FileNotFoundError, CustodyBreach):
                file_bytes = None

        qr_identifier = None
        if file_bytes is not None:
            qr = self._qr_check(doc, file_bytes)
            if qr is not None:
                results.append(qr)
                payload = qr.source_response or {}
                if payload.get("signature_valid"):
                    qr_identifier = (payload.get("data") or {}).get("id")
        if doc.doc_type in SOURCES:
            results.append(self._api_check(db, doc, qr_identifier))
        elif not results:
            results.append(Verification(
                document_id=doc.id, method=VerificationMethod.MANUAL, source_authority="No automated source",
                status=VerificationStatus.MANUAL_REVIEW, source_response={},
                reason=f"No authorised verification source is configured for '{doc.doc_type.value}'; verify manually.",
            ))

        for v in results:
            db.add(v)
        db.commit()
        for v in results:
            db.refresh(v)
            audit_service.log_event(
                db=db, action="DOCUMENT_VERIFIED", user_id=user_id, application_id=doc.application_id,
                details={"document_id": str(doc.id), "method": v.method.value, "source": v.source_authority,
                         "status": v.status.value, "identifiers_sent": v.request_identifiers or {}, "attempt": v.attempts},
            )
            if v.status == VerificationStatus.UNAVAILABLE and settings.USE_CELERY:
                from app.tasks.verification_tasks import verify_document_task
                verify_document_task.apply_async(args=[str(doc.id)], countdown=int((v.next_retry_at - datetime.now(timezone.utc)).total_seconds()))
        return results

    def _qr_check(self, doc: Document, file_bytes: bytes) -> Verification | None:
        is_pdf = file_bytes[:5] == b"%PDF-"
        try:
            qr = verify_qr(file_bytes, is_pdf)
        except Exception as e:
            logger.warning(f"QR check failed: {e}")
            return None
        if qr is None:
            return None
        base = dict(document_id=doc.id, source_response={k: v for k, v in qr.items() if k != "raw"})
        if not qr["format_ok"]:
            return Verification(**base, method=VerificationMethod.QR_CODE, source_authority="Unrecognised QR", status=VerificationStatus.MANUAL_REVIEW,
                                reason="A QR code is present but is not a recognised signed certificate; check it manually.")
        issuer = qr["issuer"]
        if not qr["signature_valid"]:
            return Verification(**base, method=VerificationMethod.DIGITAL_SIGNATURE, source_authority=authority_name(issuer),
                                status=VerificationStatus.MISMATCH,
                                reason="The QR code's digital signature is invalid: the QR contents were altered or forged.")
        spec = SOURCES.get(doc.doc_type)
        data = qr["data"] or {}
        rows = _compare(spec, doc.extracted_data or {}, data) if spec else []
        if spec and data.get("id"):
            rows.insert(0, compare_field(spec["id_field"], (doc.extracted_data or {}).get(spec["id_field"]), data["id"], "identifier"))
        status, reason = _outcome(rows, data, spec) if spec else (VerificationStatus.VERIFIED, "QR signature valid")
        if status == VerificationStatus.MISMATCH:
            reason = ("The issuer-signed QR code does not match the printed text — " + reason.split(" — ", 1)[-1]
                      + ". The printed values were likely altered after issue.")
        return Verification(**base, method=VerificationMethod.DIGITAL_SIGNATURE, source_authority=authority_name(issuer),
                            status=status, field_comparison=rows, reason=f"Signature valid (Ed25519). {reason}",
                            request_identifiers={})

    def _api_check(self, db: Session, doc: Document, qr_identifier: str | None = None) -> Verification:
        spec = SOURCES[doc.doc_type]
        authority = spec["authority"]
        ext = doc.extracted_data or {}
        ocr_identifier = ext.get(spec["id_field"])
        raster_ocr = (ext.get("ocr") or {}).get("engine") not in (None, "pdf-native")
        # A signature-verified QR carries the identifier exactly as issued; OCR of a scan may misread it
        identifier = qr_identifier or ocr_identifier
        previous = (db.query(Verification)
                    .filter(Verification.document_id == doc.id, Verification.method == VerificationMethod.API)
                    .order_by(Verification.verified_at.desc()).first())
        attempt = (previous.attempts or 1) + 1 if previous and previous.status in (VerificationStatus.UNAVAILABLE, VerificationStatus.PENDING) else 1
        base = dict(document_id=doc.id, method=VerificationMethod.API, source_authority=authority_name(authority), attempts=attempt)

        if not identifier:
            return Verification(**base, status=VerificationStatus.MANUAL_REVIEW, source_response={},
                                reason=f"No {spec['id_field'].replace('_', ' ')} could be read from the document, so the "
                                       "issuing authority could not be queried. Verify manually.")
        sent = {spec["id_field"]: identifier}  # data minimisation: only the identifier leaves
        try:
            resp = get_connector().lookup(authority, identifier)
        except SourceUnavailable as e:
            delay = backoff_delay(attempt, base=60, cap=6 * 3600)
            return Verification(**base, status=VerificationStatus.UNAVAILABLE, request_identifiers=sent, source_response={"error": str(e)},
                                next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
                                reason=f"Source unavailable: {e}. Automatic retry #{attempt} scheduled with exponential backoff.")
        if resp["status"] == "pending":
            return Verification(**base, status=VerificationStatus.PENDING, request_identifiers=sent, source_response=resp,
                                next_retry_at=datetime.now(timezone.utc) + timedelta(hours=24),
                                reason=resp.get("message", "Verification pending at the issuing authority"))
        if resp["status"] == "not_found" and raster_ocr and not qr_identifier:
            return Verification(**base, status=VerificationStatus.MANUAL_REVIEW, request_identifiers=sent, source_response=resp,
                                reason=f"No record for '{identifier}', but this number was read by OCR from a scanned image and may "
                                       "be misread. Confirm the number on the original before treating this as a mismatch.")
        if resp["status"] == "not_found":
            return Verification(**base, status=VerificationStatus.MISMATCH, request_identifiers=sent, source_response=resp,
                                field_comparison=[compare_field(spec["id_field"], identifier, None, "identifier")],
                                reason=f"No record with {spec['id_field'].replace('_', ' ')} '{identifier}' exists at {authority_name(authority)}.")
        record = resp["record"] or {}
        rows = _compare(spec, ext, record)
        if qr_identifier and ocr_identifier and qr_identifier != ocr_identifier:
            rows.insert(0, compare_field(spec["id_field"], ocr_identifier, qr_identifier, "identifier"))
        status, reason = _outcome(rows, record, spec)
        return Verification(**base, status=status, request_identifiers=sent, source_response=resp, field_comparison=rows, reason=reason)

    @staticmethod
    def latest_by_method(doc: Document) -> list[Verification]:
        latest: dict[VerificationMethod, Verification] = {}
        for v in sorted(doc.verifications, key=lambda v: v.verified_at):
            latest[v.method] = v
        return list(latest.values())

    def needs_rerun(self, doc: Document) -> bool:
        current = self.latest_by_method(doc)
        if not current:
            return True
        return any(v.status not in FINAL_STATUSES and v.status != VerificationStatus.MANUAL_REVIEW for v in current)


verification_service = VerificationService()
