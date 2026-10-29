"""Compliance rules: default AICTE checklist, versioned edits, and deterministic per-application evaluation."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.compliance_rule import ComplianceRule, RuleCategory
from app.models.document import Document
from app.models.validation_result import Severity
from app.schemas.compliance import ComplianceEvaluationResponse, ComplianceCheckItem
from app.services import rule_engine
from app.services.records_service import records_service

SCHEMA_VERSION = 5
ALL_EXISTING = ["eoa", "change_intake", "closure", "other"]
REF = "AICTE Approval Process Handbook 2026-27 — enter clause/appendix no."

# Thresholds and formulas are prototype defaults taken from commonly cited handbook norms.
# AICTE must confirm each against the current edition; admins can edit them without code changes.
DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "rule_code": "COMP-FIRE-01", "title": "Valid Fire Safety NOC", "category": RuleCategory.SAFETY, "severity": Severity.WARNING,
        "description": "Fire NOC from the competent State Fire authority, valid on the date of assessment.",
        "conditions": {"requires_doc": "fire_safety",
                       "check": {"fact": "docs.fire_safety.valid_until_iso", "op": "valid_on", "label": "Fire NOC validity"},
                       "clause": "The institution shall hold a valid Fire Safety Certificate / NOC issued by the competent authority for all buildings used for academic purposes.",
                       "fix_hint": "Upload the current Fire NOC issued by the State Fire Services."},
    },
    {
        "rule_code": "COMP-LAND-02", "title": "Minimum land area", "category": RuleCategory.INFRASTRUCTURE, "severity": Severity.CRITICAL,
        "description": "Registered land in the Trust/Society's name meeting the minimum area for the location.",
        "conditions": {"requires_doc": "land_document",
                       "check": {"fact": "docs.land_document.land_area_acres", "op": ">=", "value": 2.5, "unit": "acres", "label": "Land area"},
                       "clause": "Minimum land requirement depends on the programme and location category (rural / urban / metro); the land shall be in the name of the applicant Trust/Society. Set the threshold for the location.",
                       "fix_hint": "Upload the registered title deed showing the full contiguous land area in the Trust's name."},
    },
    {
        "rule_code": "COMP-FAC-03", "title": "Student : faculty ratio 1:20", "category": RuleCategory.ACADEMIC, "severity": Severity.CRITICAL,
        "description": "Regular faculty ≥ total students / 20, where total students = sanctioned intake × programme years.",
        "conditions": {"requires_doc": "faculty_list",
                       "check": {"fact": "docs.faculty_list.total_faculty", "op": ">=",
                                 "value": {"expr": "ceil(app.requested_intake * computed.program_years / 20)"}, "label": "Regular faculty"},
                       "clause": "Faculty : Student ratio of 1:20 for UG engineering, computed on the total sanctioned intake across all years of the programme.",
                       "fix_hint": "Declare regular faculty so that faculty ≥ (intake × programme years) / 20, and upload the updated list."},
    },
    {
        "rule_code": "COMP-CADRE-12", "title": "Faculty cadre ratio 1:2:6 (Professors)", "category": RuleCategory.ACADEMIC, "severity": Severity.CRITICAL,
        "description": "Professors ≥ one-ninth of the required faculty (cadre ratio Professor : Associate : Assistant = 1 : 2 : 6).",
        "conditions": {"requires_doc": "faculty_list",
                       "check": {"fact": "docs.faculty_list.professors_count", "op": ">=",
                                 "value": {"expr": "ceil(ceil(app.requested_intake * computed.program_years / 20) / 9)"}, "label": "Professors"},
                       "clause": "Cadre ratio of Professor : Associate Professor : Assistant Professor = 1 : 2 : 6 for UG programmes.",
                       "fix_hint": "Appoint or declare Professors in line with the 1:2:6 cadre ratio."},
    },
    {
        "rule_code": "COMP-FIN-04", "title": "Audited financials with UDIN", "category": RuleCategory.FINANCIAL, "severity": Severity.WARNING,
        "description": "Audited statements certified by a practising CA with an 18-character UDIN.",
        "conditions": {"requires_doc": "audit_report",
                       "check": {"fact": "docs.audit_report.udin", "op": "exists", "label": "ICAI UDIN"},
                       "clause": "Audited statement of accounts certified by a Chartered Accountant, bearing a UDIN generated on the ICAI portal.",
                       "fix_hint": "Upload the audited statement carrying the CA's UDIN."},
    },
    {
        "rule_code": "COMP-STAT-05", "title": "Notarised affidavit on e-stamp paper", "category": RuleCategory.STATUTORY, "severity": Severity.WARNING,
        "description": "Affidavit on non-judicial / e-stamp paper affirming adherence to AICTE norms.",
        "conditions": {"requires_doc": "affidavit",
                       "check": {"fact": "docs.affidavit.stamp_certificate_no", "op": "exists", "label": "e-Stamp certificate number"},
                       "clause": "An affidavit in the prescribed format on non-judicial stamp paper, duly notarised.",
                       "fix_hint": "Upload the notarised affidavit on e-stamp paper with a legible certificate number."},
    },
    {
        "rule_code": "COMP-NOC-06", "title": "Valid NOC from affiliating university", "category": RuleCategory.STATUTORY, "severity": Severity.WARNING,
        "description": "NOC / affiliation consent valid for the academic year.",
        "conditions": {"requires_doc": "noc",
                       "check": {"fact": "docs.noc.valid_until_iso", "op": "valid_on", "label": "University NOC validity"},
                       "clause": "NOC / consent of affiliation from the affiliating University valid for the academic year applied for.",
                       "fix_hint": "Upload the current NOC from the affiliating university."},
    },
    {
        "rule_code": "COMP-BLD-07", "title": "Classroom carpet area ≥ 66 m²", "category": RuleCategory.INFRASTRUCTURE, "severity": Severity.CRITICAL,
        "description": "Sanctioned building plan; the smallest classroom must be at least 66 m² carpet area.",
        "conditions": {"requires_doc": "building_plan",
                       "check": {"fact": "docs.building_plan.min_classroom_area_sqm", "op": ">=", "value": 66, "unit": "sqm", "label": "Smallest classroom"},
                       "clause": "Minimum carpet area of each classroom: 66 m² (instructional area norms).",
                       "fix_hint": "Upload the sanctioned plan with room-wise carpet areas; classrooms must meet 66 m²."},
    },
    {
        "rule_code": "COMP-LAB-08", "title": "Computer lab workstations", "category": RuleCategory.INFRASTRUCTURE, "severity": Severity.CRITICAL,
        "description": "Photo/video evidence of the computer lab showing the required workstations.",
        "conditions": {"requires_doc": "lab_photo",
                       "check": {"fact": "infra.computer", "op": ">=", "value": 15, "unit": "count", "label": "Computer workstations visible"},
                       "clause": "Computing facilities as prescribed for the approved intake (terminals per student ratio); set the threshold for the intake.",
                       "fix_hint": "Upload clear wide-angle photos or a walkthrough video of each computer lab."},
    },
    {
        "rule_code": "COMP-TER-09", "title": "TER fee paid for the academic year", "category": RuleCategory.FINANCIAL, "severity": Severity.WARNING,
        "applies_to": ALL_EXISTING,
        "description": "TER / processing fee recorded as paid in AICTE systems.",
        "conditions": {"check": {"fact": "records.ter_payment_current", "op": "==", "value": "paid", "label": "TER payment status"},
                       "fail_rag": "amber",
                       "clause": "Processing / TER fee for the academic year shall be paid through the AICTE portal.",
                       "fix_hint": "Pay the TER fee on the AICTE portal; payment is not yet reflected in AICTE records."},
    },
    {
        "rule_code": "COMP-DEF-10", "title": "No open deficiencies from previous cycle", "category": RuleCategory.STATUTORY, "severity": Severity.WARNING,
        "applies_to": ALL_EXISTING,
        "description": "Deficiencies recorded in the previous approval cycle are closed.",
        "conditions": {"check": {"fact": "records.open_deficiency_count", "op": "==", "value": 0, "unit": "count", "label": "Open deficiencies on record"},
                       "fail_rag": "amber",
                       "clause": "Compliance to deficiencies pointed out in the previous approval cycle shall be submitted.",
                       "fix_hint": "Submit compliance evidence for deficiencies raised in the previous cycle."},
    },
    {
        "rule_code": "COMP-INT-11", "title": "Intake within approved intake", "category": RuleCategory.ACADEMIC, "severity": Severity.CRITICAL,
        "applies_to": ["eoa"],
        "description": "An EoA application cannot raise intake; increases need a Change-in-Intake application.",
        "conditions": {"check": {"fact": "app.requested_intake", "op": "<=", "value": {"fact": "records.approved_intake"}, "unit": "count", "label": "Requested intake"},
                       "on_missing_fact": "skip",
                       "clause": "Extension of Approval is for the existing approved intake; any increase requires a separate application.",
                       "fix_hint": "Apply for the approved intake, or file a Change-in-Intake application."},
    },
    {
        "rule_code": "COMP-GEO-13", "title": "Campus boundary matches deed area (±5%)", "category": RuleCategory.INFRASTRUCTURE, "severity": Severity.CRITICAL,
        "description": "Geodesic area of the submitted campus boundary within 5% of the land area on the title deed.",
        "conditions": {"requires_doc": "campus_boundary",
                       "check": {"expr": "abs(spatial.boundary_area_acres - docs.land_document.land_area_acres) / docs.land_document.land_area_acres * 100",
                                 "op": "<=", "value": 5, "label": "Boundary vs deed area deviation (%)"},
                       "on_missing_fact": "skip",
                       "clause": "Land documents shall correspond to the actual campus; the mapped boundary is compared with the registered land area.",
                       "fix_hint": "Upload the campus boundary (GeoJSON/KML from a surveyor) covering exactly the land in the title deed."},
    },
    {
        "rule_code": "COMP-GEO-14", "title": "Mapped building footprint matches building plan (±15%)", "category": RuleCategory.INFRASTRUCTURE, "severity": Severity.CRITICAL,
        "description": "Built-up area in the sanctioned plan consistent with the buildings on the campus (±15%).",
        "conditions": {"requires_doc": "campus_boundary",
                       "check": {"fact": "spatial.footprint_vs_plan_deviation_pct", "op": "<=", "value": 15, "label": "Footprint vs plan deviation (%)"},
                       "clause": "Built-up area claimed in the sanctioned plan should be consistent with the buildings existing on the campus.",
                       "fix_hint": "Ensure the building plan's built-up area reflects the constructed buildings; upload the completion certificate if recently built."},
    },
    {
        "rule_code": "COMP-ASSET-15", "title": "Equipment asset register", "category": RuleCategory.INFRASTRUCTURE, "severity": Severity.WARNING,
        "description": "Register of laboratory equipment with make, model and serial number of each item.",
        "conditions": {"requires_doc": "asset_register",
                       "check": {"fact": "docs.asset_register.equipment_count", "op": ">=", "value": 1, "unit": "count", "label": "Equipment listed"},
                       "clause": "Laboratory equipment as prescribed shall be available; the register lists each item with its serial number.",
                       "fix_hint": "Upload the equipment register with make, model and serial number of each item."},
    },
]


class ComplianceService:
    def seed_default_rules(self, db: Session) -> None:
        """Insert missing default rules and upgrade rules written for older engine versions in place."""
        changed = False
        for spec in DEFAULT_RULES:
            existing = db.query(ComplianceRule).filter(ComplianceRule.rule_code == spec["rule_code"]).first()
            conditions = {**spec["conditions"], "schema": SCHEMA_VERSION}
            if existing is None:
                db.add(ComplianceRule(
                    rule_code=spec["rule_code"], title=spec["title"], category=spec["category"],
                    description=spec["description"], conditions=conditions, severity=spec["severity"],
                    applies_to=spec.get("applies_to", []), version=1, is_active=True, handbook_reference=REF,
                ))
                changed = True
            elif (existing.conditions or {}).get("schema") != SCHEMA_VERSION:
                existing.title, existing.description = spec["title"], spec["description"]
                existing.conditions, existing.severity = conditions, spec["severity"]
                existing.applies_to = spec.get("applies_to", [])
                existing.handbook_reference = existing.handbook_reference or REF
                existing.version = (existing.version or 1) + 1
                changed = True
        if changed:
            db.commit()

    def active_rules(self, db: Session) -> list[ComplianceRule]:
        return db.query(ComplianceRule).filter(ComplianceRule.is_active.is_(True)).order_by(ComplianceRule.rule_code).all()

    def checklist(self, db: Session, app: Application) -> list[dict[str, Any]]:
        """Documents required for this application's category (drives the institution upload checklist)."""
        out, seen = [], set()
        for r in self.active_rules(db):
            req = (r.conditions or {}).get("requires_doc")
            if req and req not in seen and rule_engine.rule_applies(r, app):
                seen.add(req)
                out.append({"doc_type": req, "rule_code": r.rule_code, "title": r.title,
                            "description": r.description, "fix_hint": (r.conditions or {}).get("fix_hint")})
        return out

    def evaluate(self, db: Session, app: Application, docs: list[Document] | None = None,
                 records: dict[str, Any] | None = None, records_status: str | None = None) -> list[dict[str, Any]]:
        if docs is None:
            docs = [d for d in app.documents if d.is_current]
        if records_status is None:
            records, records_status = records_service.fetch(app)
        facts = rule_engine.build_facts(app, docs, records, records_status)
        return [rule_engine.evaluate_rule(r, facts) for r in self.active_rules(db) if rule_engine.rule_applies(r, app)]

    def evaluate_compliance(self, db: Session, application_id: uuid.UUID) -> ComplianceEvaluationResponse:
        app = db.query(Application).filter(Application.id == application_id).first()
        if not app:
            raise ValueError("Application not found")
        outcomes = self.evaluate(db, app)
        items = [ComplianceCheckItem(
            rule_code=o["rule_code"], title=o["title"], category=RuleCategory(o["category"]), rag=o["rag"],
            status={"green": "compliant", "red": "non_compliant", "amber": "warning"}.get(o["rag"], "not_applicable"),
            message=o["message"], evidence=o.get("evidence"), rule_version=o["rule_version"],
            expected=o.get("expected"), actual=o.get("actual"), fix_hint=o.get("fix_hint"),
            clause=o.get("clause"), handbook_reference=o.get("handbook_reference"), trace=o.get("trace") or [],
        ) for o in outcomes]
        counts = {k: sum(1 for i in items if i.rag == k) for k in ("green", "amber", "red")}
        evaluated = sum(counts.values())
        return ComplianceEvaluationResponse(
            application_id=app.id, total_rules_evaluated=evaluated, compliant_count=counts["green"],
            deficiency_count=counts["red"], amber_count=counts["amber"],
            compliance_score=round(counts["green"] / evaluated * 100.0, 1) if evaluated else 100.0, results=items,
        )


compliance_service = ComplianceService()
