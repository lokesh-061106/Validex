"""Synthetic document sets for the three demo institutions.

Apex     - clean application; every source verifies (lab photos: real if provided, else placeholder).
Zenith   - problem application: whiteout-edited Fire NOC (QR + source mismatch), audit report copied
           from Apex (UDIN re-use), expired university NOC, faculty shortfall, undersized classroom,
           missing land deed, lab photo copied from Crescent, TER unpaid and an open deficiency on record.
Crescent - mostly clean; university NOC is 'verification pending' at the source; owns the original lab photo.
"""

import glob
import hashlib
import json
import os
import sys

from synthetic import (
    lab_placeholder, make_certificate, recompress_resize, tamper_whiteout,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
REAL_LAB_DIR = os.path.join(ROOT, "sample_docs", "lab_photos")

APEX = "Apex Institute of Technology & Engineering"
ZENITH = "Zenith College of Engineering & Research"
CRESCENT = "Crescent Institute of Technology"


def fire_noc(name, cert, issue, valid, issue_iso, valid_iso, place):
    return make_certificate(
        "DIRECTORATE OF FIRE & EMERGENCY SERVICES", "Government of Uttar Pradesh - Fire Prevention Wing",
        [f"Certificate No: {cert}", f"Date of Issue: {issue}", f"Valid Up to: {valid}",
         "## FIRE SAFETY CERTIFICATE (NO OBJECTION CERTIFICATE)",
         f"Certified that the educational building of {name},",
         f"located at {place}, comprising Ground + 4 floors, was inspected and found to comply",
         "with Part IV (Fire & Life Safety) of the National Building Code of India.",
         "Issued by: Chief Fire Officer, Directorate of Fire & Emergency Services"],
        qr=("fire_services", {"id": cert, "holder": name, "issue_date": issue_iso, "valid_until": valid_iso}),
        seal_text="FIRE SERVICES",
    )


def audit_report(client, udin, membership, firm):
    return make_certificate(
        f"M/S {firm.upper()}", "Chartered Accountants",
        ["INDEPENDENT AUDITOR'S REPORT", f"To the Governing Body of {client}",
         "Financial Year: 2025-2026", f"UDIN: {udin}", f"Membership No: {membership}",
         "## STATEMENT OF INCOME AND EXPENDITURE",
         "Total Income: Rs 14,85,50,000", "Total Expenditure: Rs 12,40,20,000",
         "In our opinion the financial statements give a true and fair view of the state of affairs."],
        qr=("icai_udin", {"id": udin, "client": client, "financial_year": "2025-2026", "membership_no": membership}),
        seal_text="CHARTERED ACCT",
    )


def land_deed(owner, deed, acres, survey, reg_date):
    return make_certificate(
        "OFFICE OF THE SUB-REGISTRAR", "Department of Stamps & Registration - Title Deed",
        [f"Deed Number: {deed}", f"Date of Registration: {reg_date}", "## SALE DEED FOR INSTITUTIONAL CAMPUS",
         f"This registered sale deed conveys contiguous land measuring {acres} Acres",
         f"situated at Survey No: {survey}, Tehsil Dadri, District Gautam Buddh Nagar.",
         f"Registered in favour of: {owner}.",
         "The land is free from encumbrances, mortgages and legal disputes."],
        qr=("land_records", {"id": deed, "owner": owner, "area_acres": acres}), seal_text="SUB-REGISTRAR",
    )


def faculty_roster(code: str, prof: int, assoc: int, asst: int) -> list[dict]:
    """Synthetic faculty rows. PANs use the VXD prefix so they are recognisably fake."""
    designations = ["Professor"] * prof + ["Associate Professor"] * assoc + ["Assistant Professor"] * asst
    rows = []
    for i, d in enumerate(designations):
        h = hashlib.sha256(f"{code}-{i}".encode()).hexdigest().upper()
        letters = "".join(c for c in h if c.isalpha())[:3].ljust(3, "Q")
        digits = "".join(c for c in h if c.isdigit())[:4].ljust(4, "7")
        rows.append({"name": f"{code} Faculty {i + 1:02d}", "designation": d,
                     "qualification": "Ph.D" if d != "Assistant Professor" else "M.Tech",
                     "pan": f"VXD{letters[0]}{letters[1]}{digits}{letters[2]}",
                     "faculty_id": f"FAC-{int(hashlib.sha256(code.encode()).hexdigest(), 16) % 90 + 10}{i + 1:04d}",
                     "bio": f"BIO-{h[:8]}"})
    return rows


def faculty_list(name, roster: list[dict]):
    prof = sum(1 for r in roster if r["designation"] == "Professor")
    assoc = sum(1 for r in roster if r["designation"] == "Associate Professor")
    asst = sum(1 for r in roster if r["designation"] == "Assistant Professor")
    rows = [["Name", "Designation", "Qual.", "PAN", "AICTE Faculty ID", "Biometric ref."]]
    rows += [[r["name"], r["designation"], r["qualification"], r["pan"], r["faculty_id"], r["bio"]] for r in roster]
    return make_certificate(
        f"{name.upper()} - APPROVED FACULTY LIST", "Regular teaching staff as on 01/07/2026",
        [f"Professor: {prof}", f"Associate Professor: {assoc}", f"Assistant Professor: {asst}"],
        table=rows, seal_text="PRINCIPAL",
    )


def asset_register(name, items: list[tuple[str, str, str]]):
    rows = [["Equipment", "Location", "Serial No."]] + [[d, loc, f"S/N: {sn}"] for d, loc, sn in items]
    return make_certificate(
        f"{name.upper()} - LABORATORY EQUIPMENT ASSET REGISTER", "Asset register as on 01/07/2026",
        ["Equipment register of laboratories (make, model and serial number)."], table=rows, seal_text="STORES OFFICER",
    )


def campus_boundary(permanent_id: str) -> bytes:
    from app.mock_authority.geodata import campus_geojson
    return json.dumps(campus_geojson(permanent_id), indent=1).encode()


def affidavit(name, stamp, deponent):
    return make_certificate(
        "NON-JUDICIAL e-STAMP PAPER", "Government of Uttar Pradesh",
        [f"Stamp Certificate No: {stamp}", "## AFFIDAVIT",
         f"I, {deponent}, Principal, on behalf of {name},",
         "do hereby solemnly affirm that the institution complies with the AICTE Approval Process Handbook,",
         "the information furnished in the application is true, and no deviation will be made.",
         "Notary Public: Adv. M. K. Saxena", "Verified at Greater Noida on 15/01/2026"],
        qr=("estamp", {"id": stamp, "party": name}), seal_text="NOTARY PUBLIC",
    )


def university_noc(name, noc, issue, valid, valid_iso):
    return make_certificate(
        "DR. A.P.J. ABDUL KALAM TECHNICAL UNIVERSITY", "Affiliation Section, Lucknow",
        [f"NOC No: {noc}", f"Date of Issue: {issue}", f"Valid Up to: {valid}",
         "## NO OBJECTION CERTIFICATE FOR CONTINUATION OF AFFILIATION",
         f"Certified that {name}, is an affiliated institution and the University",
         "has no objection to its continuation of approval for the stated period.",
         "Issued by the Registrar, Dr. A.P.J. Abdul Kalam Technical University"],
        qr=("university_noc", {"id": noc, "institution": name, "valid_until": valid_iso}), seal_text="REGISTRAR",
    )


def building_plan(authority, approval, area, rooms, floors: int = 3, coverage: str = "4,625"):
    """rooms: [(stated_sqm, length_m, width_m)]"""
    return make_certificate(
        authority, "Sanctioned Building Plan - Institutional",
        [f"Plan Approval No: {approval}", f"Approved by: Chief Architect Planner, {authority.title()}",
         f"Total Built-up Area: {area} Sq M", f"Floors: G+{floors}", f"Ground Coverage: {coverage} Sq M",
         "## ROOM-WISE CARPET AREA"] +
        [f"Classroom C-{101 + i}: {a:g} sq m ({l:g} m x {w:g} m)" for i, (a, l, w) in enumerate(rooms)],
        seal_text="ARCHITECT",
    )


def lab_photos() -> list[tuple[str, bytes]]:
    real = sorted(glob.glob(os.path.join(REAL_LAB_DIR, "*.jp*g")) + glob.glob(os.path.join(REAL_LAB_DIR, "*.png")))
    if real:
        return [(os.path.basename(p), open(p, "rb").read()) for p in real]
    return []


def build() -> dict[str, dict]:
    real = lab_photos()
    apex_lab = real[0] if real else ("apex_lab_placeholder.jpg", lab_placeholder(1, "APEX"))
    crescent_lab = real[1] if len(real) > 1 else ("crescent_lab_placeholder.jpg", lab_placeholder(2, "CRESCENT"))

    apex_roster = faculty_roster("APX", 8, 16, 48)        # 72 = 1440 students / 20
    crescent_roster = faculty_roster("CRS", 6, 12, 30)    # 48 = 960 / 20
    zenith_roster = faculty_roster("ZEN", 2, 3, 4)        # 9, required 60
    # Collusion: two Zenith "faculty" are Apex staff (same PAN); one shares a biometric ID with a different Crescent PAN
    zenith_roster[0] = {**apex_roster[4], "designation": zenith_roster[0]["designation"]}
    zenith_roster[2] = {**apex_roster[9], "designation": zenith_roster[2]["designation"]}
    zenith_roster[5] = {**zenith_roster[5], "bio": crescent_roster[3]["bio"]}
    crescent_assets = [("Dell OptiPlex desktop", "Computer Lab 1", f"CRS-DT-{2001 + i}") for i in range(15)]
    apex_assets = [("HP ProDesk desktop", "Computer Lab 1", f"APX-DT-{1001 + i}") for i in range(20)]
    zenith_assets = ([crescent_assets[i] for i in range(2, 6)]                     # serials also in Crescent's register
                     + [("Lenovo ThinkCentre desktop", "Lab 1", f"ZEN-DT-{3001 + i}") for i in range(6)])

    zenith_fire_genuine = fire_noc(ZENITH, "DFS/HQ/2022/NOC-44102", "16/03/2022", "15/03/2025", "2022-03-16", "2025-03-15", "Sector 62, Noida 201309")
    apex_audit = audit_report(APEX, "26054321BKAPEX1234", "054321", "R. Sharma & Associates")

    return {
        "apex": {
            "name": APEX, "email": "principal@apex.edu.in", "permanent_id": "1-2345678901", "intake": 360,
            "number": "AICTE-2026-100001",
            "docs": [
                ("fire_safety", "fire_noc_2024.pdf", fire_noc(APEX, "DFS/HQ/2024/NOC-98421", "10/01/2024", "31/12/2027", "2024-01-10", "2027-12-31", "Knowledge Park III, Greater Noida 201310")),
                ("audit_report", "audited_statement_2025_26.pdf", apex_audit),
                ("land_document", "land_title_deed.pdf", land_deed("Apex Educational & Research Foundation Trust", "REG-DEED-2021-98124", 12.5, "142/1, 142/2", "14/08/2021")),
                ("faculty_list", "faculty_list_2026_27.pdf", faculty_list(APEX, apex_roster)),
                ("affidavit", "affidavit_estamp.pdf", affidavit(APEX, "IN-UP98421054231801", "Dr. S. K. Ramanathan")),
                ("noc", "aktu_noc_2026.pdf", university_noc(APEX, "AKTU/NOC/2026/1187", "01/06/2026", "31/05/2027", "2027-05-31")),
                ("building_plan", "sanctioned_building_plan.pdf", building_plan("GREATER NOIDA DEVELOPMENT AUTHORITY", "GNIDA/BP/2019/3341", "18,500",
                                                                                [(72, 8, 9), (70, 7, 10), (68, 8.5, 8), (75, 7.5, 10)], floors=3, coverage="4,625")),
                ("asset_register", "equipment_register.pdf", asset_register(APEX, apex_assets)),
                ("campus_boundary", "campus_boundary.geojson", campus_boundary("1-2345678901")),
                ("lab_photo", apex_lab[0], apex_lab[1]),
            ],
        },
        "zenith": {
            "name": ZENITH, "email": "principal@zenith.edu.in", "permanent_id": "1-9876543210", "intake": 300,
            "number": "AICTE-2026-100002",
            "docs": [
                ("fire_safety", "fire_noc_renewed.pdf", tamper_whiteout(zenith_fire_genuine, "15/03/2025", "31/12/2027")),
                # Copied from Apex with the client name changed: UDIN belongs to another institution
                ("audit_report", "audit_report_2025_26.pdf", _swap_text(apex_audit, APEX, ZENITH)),
                ("faculty_list", "faculty_list.pdf", faculty_list(ZENITH, zenith_roster)),
                ("affidavit", "affidavit.pdf", affidavit(ZENITH, "IN-UP77120931188402", "Dr. R. Malhotra")),
                ("noc", "university_noc.pdf", university_noc(ZENITH, "AKTU/NOC/2024/0932", "01/06/2024", "31/05/2025", "2025-05-31")),
                ("building_plan", "building_plan.pdf", building_plan("NOIDA AUTHORITY", "NOIDA/BP/2018/2210", "9,800",
                                                                     [(70, 7, 9), (58, 7.25, 8), (66, 6, 11)], floors=2, coverage="3,400")),
                ("asset_register", "asset_register.pdf", asset_register(ZENITH, zenith_assets)),
                ("campus_boundary", "campus.geojson", campus_boundary("1-9876543210")),
                ("lab_photo", "computer_lab_1.jpg", recompress_resize(crescent_lab[1], 0.85, 80)),
            ],
        },
        "crescent": {
            "name": CRESCENT, "email": "principal@crescent.edu.in", "permanent_id": "1-5550001112", "intake": 240,
            "number": "AICTE-2026-100003",
            "docs": [
                ("fire_safety", "fire_noc.pdf", fire_noc(CRESCENT, "DFS/HQ/2023/NOC-61177", "01/07/2023", "30/06/2028", "2023-07-01", "2028-06-30", "Techzone IV, Greater Noida 201318")),
                ("audit_report", "audit_2025_26.pdf", audit_report(CRESCENT, "26112233CRESC56789", "112233", "Mehta Gupta & Co.")),
                ("land_document", "land_deed.pdf", land_deed("Crescent Education Society", "REG-DEED-2019-55310", 10.2, "77/4", "02/05/2019")),
                ("faculty_list", "faculty_list.pdf", faculty_list(CRESCENT, crescent_roster)),
                ("affidavit", "affidavit.pdf", affidavit(CRESCENT, "IN-UP55500011120003", "Dr. A. Fernandes")),
                ("noc", "aktu_noc.pdf", university_noc(CRESCENT, "AKTU/NOC/2026/1290", "01/06/2026", "31/05/2027", "2027-05-31")),
                ("building_plan", "building_plan.pdf", building_plan("GREATER NOIDA DEVELOPMENT AUTHORITY", "GNIDA/BP/2017/1120", "14,200",
                                                                     [(68, 8.5, 8), (70, 7, 10), (66, 6, 11)], floors=3, coverage="3,600")),
                ("asset_register", "asset_register.pdf", asset_register(CRESCENT, crescent_assets)),
                ("campus_boundary", "campus_boundary.geojson", campus_boundary("1-5550001112")),
                ("lab_photo", crescent_lab[0], crescent_lab[1]),
            ],
        },
    }


def _swap_text(pdf: bytes, old: str, new: str) -> bytes:
    """Regenerate-style copy: the forger retyped the report with a different client name (no visual edit traces)."""
    import fitz
    doc = fitz.open(stream=pdf, filetype="pdf")
    page = doc[0]
    for hit in page.search_for(old):
        page.add_redact_annot(hit, fill=(1, 1, 1))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    hit_y = 150 + 17  # line 2 of the body
    page.insert_text((50 + fitz.get_text_length("To the Governing Body of ", fontname="helv", fontsize=10), hit_y), new,
                     fontsize=10, fontname="helv")
    return doc.tobytes(garbage=3, deflate=True)
