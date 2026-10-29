"""Application triage: turns rules, document evidence, source verifications, duplicates, the collusion
graph, spatial checks and AICTE records into evidence-linked findings labelled

    GREEN  auto-pass (not stored as findings; visible as passed rules)
    AMBER  missing / expired / unreadable -> encrypted clarification request to the institution
    RED    anomaly or deterministic failure -> an officer must confirm or override

The official application status only moves SUBMITTED -> UNDER_REVIEW here; decisions stay with officers.
Findings are visible only in the officers' console (the college portal is blind to them).
"""

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.application import AIRecommendation, Application, ApplicationStatus
from app.models.document import Document, DocumentStatus, DocumentType
from app.models.notification import Notification, NotificationStatus
from app.models.validation_result import CheckType, Severity, ValidationResult
from app.models.verification import VerificationMethod, VerificationStatus
from app.services.audit_service import audit_service
from app.services.compliance_service import compliance_service
from app.services.matching import compare_field
from app.services.records_service import records_service
from app.services.rule_engine import AMBER, GREEN, RED
from app.services.verification_service import verification_service
from app.services.workflow_service import transition_allowed

logger = logging.getLogger(__name__)

RAG_SEVERITY = {RED: Severity.CRITICAL, AMBER: Severity.WARNING, GREEN: Severity.INFO}
RAG_POINTS = {RED: 25.0, AMBER: 8.0, GREEN: 0.0}
SEVERITY_POINTS = {Severity.CRITICAL: 25.0, Severity.WARNING: 8.0, Severity.INFO: 0.0}
METHOD_LABEL = {"api": "registry lookup", "digital_signature": "signed QR", "qr_code": "QR code", "manual": "manual"}
NAME_FIELDS = ["holder", "client_name", "institution_name", "deponent_institution"]


def fingerprint(application_id, check: CheckType, rule_code: str | None, document_id, finding: str) -> str:
    stable = re.sub(r"\s+", " ", finding.strip().lower())
    raw = f"{application_id}|{check.value}|{rule_code or ''}|{document_id or ''}|{stable}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _finding(app: Application, check: CheckType, rag: str, finding: str, evidence: str | None = None,
             document: Document | None = None, fix_hint: str | None = None, details: dict | None = None,
             confidence: float = 1.0, rule: dict[str, Any] | None = None, actionable_by: str = "officer") -> ValidationResult:
    finding = finding[:500]
    return ValidationResult(
        application_id=app.id, document_id=document.id if document else None, check_type=check,
        severity=RAG_SEVERITY[rag], rag=rag, actionable_by=actionable_by,
        finding=finding, evidence=(evidence or "")[:2000] or None, fix_hint=fix_hint, details=details or {},
        confidence=confidence, rule_code=rule["rule_code"] if rule else None, rule_version=rule["rule_version"] if rule else None,
        fingerprint=fingerprint(app.id, check, rule["rule_code"] if rule else None, document.id if document else None, finding),
    )


class ValidationService:
    def validate_application(self, db: Session, application_id: uuid.UUID, user_id: uuid.UUID | None = None) -> dict[str, Any]:
        app = db.query(Application).filter(Application.id == application_id).first()
        if not app:
            raise ValueError("Application not found")
        docs = [d for d in app.documents if d.is_current]
        doc_by_type: dict[DocumentType, Document] = {}
        for d in docs:
            doc_by_type.setdefault(d.doc_type, d)

        # Retry source verifications that are pending / unavailable / never run
        for d in docs:
            if verification_service.supports(d) and d.status != DocumentStatus.PROCESSING and verification_service.needs_rerun(d):
                verification_service.verify_document(db, d.id, user_id=user_id)
                db.refresh(d)

        db.query(ValidationResult).filter(ValidationResult.application_id == app.id).delete()
        db.commit()

        records, records_status = records_service.fetch(app)
        outcomes = compliance_service.evaluate(db, app, docs, records, records_status)
        findings: list[ValidationResult] = []
        findings += self._rule_findings(app, outcomes, doc_by_type)
        findings += self._document_findings(app, docs)
        findings += self._verification_findings(app, docs)
        findings += self._consistency_findings(app, docs, records, records_status)
        findings += self._graph_findings(db, app)

        for f in findings:
            db.add(f)

        counts = {k: sum(1 for f in findings if f.rag == k) for k in (RED, AMBER)}
        counts[GREEN] = sum(1 for o in outcomes if o["rag"] == GREEN)
        contributions = [{"finding": f.finding, "rag": f.rag, "severity": f.severity.value, "points": RAG_POINTS[f.rag]}
                         for f in findings if RAG_POINTS[f.rag] > 0 and f.actionable_by != "system"]
        app.risk_score = round(min(sum(c["points"] for c in contributions), 100.0), 1)
        app.ai_recommendation, app.ai_summary = self._recommend(findings)
        app.ai_reviewed_at = datetime.now(timezone.utc)
        if app.status == ApplicationStatus.SUBMITTED and transition_allowed(
                db, ApplicationStatus.SUBMITTED, ApplicationStatus.UNDER_REVIEW, "system"):
            old_status = app.status
            app.status = ApplicationStatus.UNDER_REVIEW
        else:
            old_status = None
        db.commit()

        if old_status is not None:
            audit_service.log_event(db=db, action="APPLICATION_STATUS_TRANSITIONED", user_id=None,
                                    application_id=app.id,
                                    details={"from": old_status.value, "to": app.status.value, "reason": "Automated prescreen completed"},
                                    actor_role="system")

        resolved = self._resolve_notifications(db, app, findings)
        audit_service.log_event(
            db=db, action="AI_PRESCREENING_COMPLETED", user_id=user_id, application_id=app.id,
            details={
                "risk_score": app.risk_score, "recommendation": app.ai_recommendation.value,
                "red": counts[RED], "amber": counts[AMBER], "green_rules": counts[GREEN],
                "rules_applied": [{"code": o["rule_code"], "version": o["rule_version"], "rag": o["rag"]} for o in outcomes],
                "records_source": {"permanent_id": app.permanent_id, "status": records_status},
                "documents_checked": [str(d.id) for d in docs],
                "notices_resolved": resolved,
            },
        )
        return {
            "application_id": str(app.id), "risk_score": app.risk_score,
            "ai_recommendation": app.ai_recommendation.value, "ai_summary": app.ai_summary,
            "status": app.status.value, "red_count": counts[RED], "amber_count": counts[AMBER], "green_rules": counts[GREEN],
            "critical_count": counts[RED], "warning_count": counts[AMBER],
            "findings_count": len(findings), "risk_contributions": contributions, "records_status": records_status,
        }

    # ------------------------------------------------------------------ rules
    @staticmethod
    def _rule_findings(app: Application, outcomes: list[dict[str, Any]], doc_by_type: dict) -> list[ValidationResult]:
        out = []
        for o in outcomes:
            if o["rag"] in (GREEN, "not_applicable"):
                continue
            doc = doc_by_type.get(DocumentType(o["doc_type"])) if o.get("doc_type") else None
            fact = o.get("fact") or ""
            kind = o.get("kind")
            check = (CheckType.COMPLETENESS if kind == "missing_document"
                     else CheckType.EXPIRY if kind == "expired"
                     else CheckType.RECORDS if fact.startswith("records.")
                     else CheckType.INFRASTRUCTURE if fact.startswith(("infra.", "spatial.")) or "spatial." in str(o.get("trace"))
                     else CheckType.COMPLIANCE)
            field = fact.split(".")[-1] if fact.startswith("docs.") else None
            loc = ((doc.extracted_data or {}).get("field_locations") or {}).get(field.replace("_iso", "")) if doc and field else None
            out.append(_finding(
                app, check, o["rag"], f"{o['title']}: {o['message']}",
                evidence=(f"Rule {o['rule_code']} v{o['rule_version']}. " + " | ".join(o.get("trace") or [])
                          + (f" (source: {doc.original_filename})" if doc else "")),
                document=doc, fix_hint=o.get("fix_hint"), rule=o, actionable_by=o.get("actionable_by") or "officer",
                details={"rule": o, "boxes": [loc] if loc and "x" in loc else []},
                confidence=1.0,
            ))
        return out

    # -------------------------------------------------------------- documents
    @staticmethod
    def _document_findings(app: Application, docs: list[Document]) -> list[ValidationResult]:
        out = []
        for d in docs:
            data = d.extracted_data or {}
            if d.status in (DocumentStatus.PENDING, DocumentStatus.PROCESSING):
                out.append(_finding(app, CheckType.COMPLETENESS, AMBER, f"{d.original_filename} is still being processed",
                                    document=d, details={"stage": d.processing_stage}, actionable_by="system"))
                continue
            if d.status == DocumentStatus.FAILED:
                out.append(_finding(app, CheckType.COMPLETENESS, AMBER, f"{d.original_filename} could not be read",
                                    evidence=d.processing_stage, document=d, actionable_by="institution",
                                    fix_hint="Re-upload a clear PDF or image of this document."))
                continue

            custody = data.get("custody") or {}
            if custody and not custody.get("watermarked"):
                out.append(_finding(app, CheckType.CONSISTENCY, AMBER, f"{d.original_filename}: chain-of-custody watermark missing",
                                    evidence=custody.get("note"), document=d, actionable_by="system"))

            forensics = data.get("forensics") or {}
            if forensics.get("is_suspected"):
                indicators = forensics.get("indicators", [])
                out.append(_finding(
                    app, CheckType.FORGERY, RED,
                    f"Possible alteration in {d.original_filename} ({forensics.get('level')} likelihood) — confirm manually",
                    evidence="; ".join(f"[{i['method']}, {i['strength']}] {i['description']}" for i in indicators),
                    document=d, confidence=0.9 if forensics.get("level") == "high" else 0.6,
                    details={"indicators": indicators, "boxes": [b for i in indicators for b in i.get("boxes", [])],
                             "disclaimer": forensics.get("disclaimer")},
                ))

            for dup in data.get("duplicates") or []:
                if dup.get("same_application") and dup["match"] == "exact_file":
                    continue  # same file uploaded twice in one application: not an anomaly
                out.append(_finding(app, CheckType.DUPLICATE, RED,
                                    f"{d.original_filename}: {dup['reason']} — also in {dup['application_number']} ({dup['institution_name']})",
                                    evidence=dup["reason"], document=d, details={"duplicate": dup},
                                    confidence=0.95 if dup["match"] != "near_duplicate_image" else 0.8))

            cls = data.get("classification") or {}
            if cls.get("mismatch"):
                out.append(_finding(app, CheckType.COMPLETENESS, AMBER, f"Document in the wrong checklist slot: {d.original_filename}",
                                    evidence=cls["mismatch"], document=d, actionable_by="institution",
                                    fix_hint=f"Upload the {d.doc_type.value.replace('_', ' ')} in this slot."))
            ocr = data.get("ocr") or {}
            if ocr and ocr.get("confidence", 1) < 0.6 and d.doc_type not in (DocumentType.LAB_PHOTO, DocumentType.CAMPUS_BOUNDARY):
                out.append(_finding(app, CheckType.COMPLETENESS, AMBER, f"{d.original_filename} is not legible enough to read",
                                    evidence=f"OCR engine {ocr.get('engine')}, confidence {ocr.get('confidence', 0):.0%}",
                                    document=d, actionable_by="institution", fix_hint="Upload the digital original or a 300 dpi scan."))

            cv = data.get("infrastructure")
            if cv:
                for issue in (cv.get("evidence_quality") or {}).get("issues", []):
                    out.append(_finding(app, CheckType.INFRASTRUCTURE, AMBER, f"{d.original_filename}: {issue}", document=d,
                                        actionable_by="institution", fix_hint="Upload a clear, well-lit, wide-angle photo or walkthrough video."))
                if cv.get("status") != "analyzed":
                    out.append(_finding(app, CheckType.INFRASTRUCTURE, AMBER,
                                        f"{d.original_filename}: automated equipment detection unavailable — check manually", document=d))
            if d.doc_type == DocumentType.BUILDING_PLAN:
                from app.services.spatial_service import spatial_service
                for issue in spatial_service.blueprint_issues(data):
                    out.append(_finding(app, CheckType.INFRASTRUCTURE, RED, f"{d.original_filename}: {issue['message']}",
                                        evidence=issue["evidence"], document=d, details={"room_dimensions": data.get("room_dimensions")}))
            spatial = data.get("spatial") or {}
            for issue in spatial.get("issues", []):
                out.append(_finding(app, CheckType.INFRASTRUCTURE, issue.get("rag", RED), f"{d.original_filename}: {issue['message']}",
                                    evidence=issue.get("evidence"), document=d, details={"spatial": spatial},
                                    actionable_by=issue.get("actionable_by", "officer"), fix_hint=issue.get("fix_hint")))
        return out

    # ----------------------------------------------------------- verification
    @staticmethod
    def _verification_findings(app: Application, docs: list[Document]) -> list[ValidationResult]:
        out = []
        rag_map = {
            VerificationStatus.MISMATCH: (RED, "officer"), VerificationStatus.EXPIRED: (AMBER, "institution"),
            VerificationStatus.MANUAL_REVIEW: (AMBER, "officer"), VerificationStatus.UNAVAILABLE: (AMBER, "system"),
            VerificationStatus.PENDING: (AMBER, "system"),
        }
        for d in docs:
            for v in verification_service.latest_by_method(d):
                if v.status == VerificationStatus.VERIFIED:
                    continue
                if v.method == VerificationMethod.MANUAL and v.source_authority == "No automated source":
                    continue
                rag, who = rag_map[v.status]
                label = {"mismatch": "mismatch detected", "expired": "expired at source", "manual_review": "manual review required",
                         "unavailable": "source unavailable (retry scheduled)", "pending": "verification pending"}[v.status.value]
                out.append(_finding(
                    app, CheckType.VERIFICATION, rag,
                    f"{d.original_filename}: {v.source_authority} ({METHOD_LABEL.get(v.method.value, v.method.value)}) — {label}",
                    evidence=v.reason, document=d, actionable_by=who,
                    confidence=0.97 if v.status in (VerificationStatus.MISMATCH, VerificationStatus.EXPIRED) else 0.7,
                    fix_hint="Renew the certificate with the issuing authority and upload the new one." if v.status == VerificationStatus.EXPIRED else None,
                    details={"verification_id": str(v.id), "method": v.method.value, "status": v.status.value,
                             "field_comparison": v.field_comparison or [], "attempts": v.attempts,
                             "next_retry_at": v.next_retry_at.isoformat() if v.next_retry_at else None},
                ))
        return out

    # ------------------------------------------------------------ consistency
    @staticmethod
    def _consistency_findings(app: Application, docs: list[Document], records: dict | None, records_status: str) -> list[ValidationResult]:
        out = []
        if records_status == "unavailable":
            out.append(_finding(app, CheckType.RECORDS, AMBER, "AICTE institutional records temporarily unavailable; record checks will re-run",
                                actionable_by="system"))
        elif records_status == "not_found":
            out.append(_finding(app, CheckType.RECORDS, AMBER, f"No AICTE record found for permanent ID {app.permanent_id}",
                                actionable_by="institution", fix_hint="Check the AICTE permanent institute ID on the application."))
        elif records_status == "no_permanent_id" and app.category.value != "new_institution":
            out.append(_finding(app, CheckType.RECORDS, AMBER, "Application has no AICTE permanent ID",
                                actionable_by="institution", fix_hint="Enter the AICTE permanent institute ID on the application."))

        reference_names = [("application", app.institution_name)]
        if records:
            reference_names.append(("AICTE records", records.get("name")))
        for d in docs:
            data = d.extracted_data or {}
            for field in NAME_FIELDS:
                value = data.get(field)
                if not value:
                    continue
                rows = [compare_field(f"{field} vs {src}", value, ref, "name") for src, ref in reference_names if ref]
                bad = [r for r in rows if r["match"] is False]
                if bad:
                    loc = (data.get("field_locations") or {}).get(field)
                    out.append(_finding(
                        app, CheckType.CONSISTENCY, RED, f"Institution name on {d.original_filename} does not match",
                        evidence="; ".join(f"'{r['submitted']}' vs {r['field'].split(' vs ')[1]} '{r['official']}' ({r['reason']})" for r in bad),
                        document=d, confidence=0.85, details={"field_comparison": rows, "boxes": [loc] if loc and "x" in loc else []},
                    ))
                break

        if records:
            land = next((d for d in docs if d.doc_type == DocumentType.LAND_DOCUMENT), None)
            if land:
                rows = [compare_field("land_area_acres", (land.extracted_data or {}).get("land_area_acres"), records.get("land_area_acres"), "number"),
                        compare_field("owner vs trust on record", (land.extracted_data or {}).get("owner"), records.get("trust"), "name")]
                bad = [r for r in rows if r["match"] is False]
                if bad:
                    out.append(_finding(app, CheckType.RECORDS, RED, "Land deed differs from AICTE records",
                                        evidence="; ".join(f"{r['field']}: {r['reason']}" for r in bad), document=land,
                                        details={"field_comparison": rows}))
            fac = next((d for d in docs if d.doc_type == DocumentType.FACULTY_LIST), None)
            declared = (fac.extracted_data or {}).get("total_faculty") if fac else None
            on_record = records.get("faculty_on_record")
            if declared and on_record and declared > on_record * 1.25:
                out.append(_finding(app, CheckType.RECORDS, RED, f"Faculty list declares {declared} faculty but AICTE records show {on_record}",
                                    evidence="Declared faculty exceed the AICTE faculty register by more than 25%.", document=fac))
        return out

    # ---------------------------------------------------------- collusion graph
    @staticmethod
    def _graph_findings(db: Session, app: Application) -> list[ValidationResult]:
        try:
            from app.services.graph_service import graph_service
            links = graph_service.collusion_for_application(db, app)
        except Exception as e:  # graph is an additional control; never block screening
            logger.warning(f"Collusion graph unavailable: {e}")
            return [_finding(app, CheckType.DUPLICATE, AMBER, "Collusion graph check could not run; re-run screening",
                             evidence=str(e)[:300], actionable_by="system")]
        out = []
        for link in links:
            out.append(_finding(app, CheckType.DUPLICATE, RED, link["finding"], evidence=link["evidence"],
                                details={"graph": link}, confidence=link.get("confidence", 0.95)))
        return out

    # --------------------------------------------------------- recommendation
    @staticmethod
    def _recommend(findings: list[ValidationResult]) -> tuple[AIRecommendation, str]:
        red = [f for f in findings if f.rag == RED]
        authenticity = [f for f in red if f.check_type in (CheckType.FORGERY, CheckType.VERIFICATION, CheckType.DUPLICATE, CheckType.CONSISTENCY)]
        spatial = [f for f in red if f.check_type == CheckType.INFRASTRUCTURE]
        amber_inst = [f for f in findings if f.rag == AMBER and f.actionable_by == "institution"]
        if authenticity:
            return AIRecommendation.DEFICIENCY, (f"{len(red)} red item(s) need officer confirmation, including {len(authenticity)} "
                                                 "authenticity anomaly(ies). Confirm or override each before deciding.")
        if red and len(spatial) == len(red):
            return AIRecommendation.INSPECTION, f"{len(red)} infrastructure/spatial discrepancy(ies): additional evidence or physical inspection suggested."
        if red:
            return AIRecommendation.DEFICIENCY, f"{len(red)} deterministic rule failure(s) need officer confirmation."
        if amber_inst:
            return AIRecommendation.CLARIFICATION, f"{len(amber_inst)} item(s) missing, expired or unreadable: send a clarification request."
        return AIRecommendation.FORWARD, "All rules green and sources verified. Forward for the competent authority's decision."

    @staticmethod
    def _resolve_notifications(db: Session, app: Application, findings: list[ValidationResult]) -> int:
        open_prints = {f.fingerprint for f in findings if f.rag == AMBER and f.actionable_by == "institution"}
        open_codes = {f.rule_code for f in findings if f.rag == AMBER and f.rule_code}
        resolved = 0
        for n in db.query(Notification).filter(Notification.application_id == app.id,
                                               Notification.status != NotificationStatus.RESOLVED).all():
            prints = {i.get("fingerprint") for i in n.items if i.get("fingerprint")}
            codes = {i.get("rule_code") for i in n.items if i.get("rule_code")}
            if not (prints & open_prints) and not (codes & open_codes):
                n.status = NotificationStatus.RESOLVED
                resolved += 1
        db.commit()
        return resolved


validation_service = ValidationService()
