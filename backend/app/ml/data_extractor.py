"""Structured field extraction from OCR text using domain-specific patterns.

Every extracted date also gets an ISO twin (e.g. valid_until -> valid_until_iso) so rules
can compare dates regardless of the printed format.
"""

import re
from typing import Any

from app.ml.dates import DATE_PATTERN, to_iso
from app.models.document import DocumentType

NAME_LINE = r"([A-Z][A-Za-z.&,'\- ]{3,120}?)"


def _search(pattern: str, text: str, flags=re.IGNORECASE) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip(" .,:;") if m else None


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


class DataExtractor:
    """Extracts domain-specific structured metadata from OCR text."""

    def extract_fields(self, text: str, doc_type: DocumentType) -> dict[str, Any]:
        extracted: dict[str, Any] = {}
        handler = {
            DocumentType.FIRE_SAFETY: self._extract_fire_safety,
            DocumentType.AUDIT_REPORT: self._extract_audit_report,
            DocumentType.LAND_DOCUMENT: self._extract_land_document,
            DocumentType.FACULTY_LIST: self._extract_faculty_list,
            DocumentType.AFFIDAVIT: self._extract_affidavit,
            DocumentType.BUILDING_PLAN: self._extract_building_plan,
            DocumentType.NOC: self._extract_noc,
            DocumentType.ASSET_REGISTER: self._extract_asset_register,
        }.get(doc_type)
        if handler:
            extracted.update({k: v for k, v in handler(text).items() if v not in (None, "", [])})
        extracted.update(self._extract_common(text))

        for key in [k for k in extracted if k.endswith(("_date", "valid_until")) and isinstance(extracted[k], str)]:
            iso = to_iso(extracted[key])
            if iso:
                extracted[f"{key}_iso"] = iso
        return extracted

    def _extract_common(self, text: str) -> dict[str, Any]:
        common: dict[str, Any] = {}
        dates = re.findall(DATE_PATTERN, text, re.IGNORECASE)
        if dates:
            common["detected_dates"] = dates[:8]
        pincodes = re.findall(r"\b([1-9][0-9]{5})\b", text)
        if pincodes:
            common["pincodes"] = sorted(set(pincodes))
        return common

    def _holder(self, text: str) -> str | None:
        return _search(
            r"(?:certified that|issued to|in favour of|institution name|name of (?:the )?institution)"
            r"[:\s]+(?:the\s+)?(?:educational building\s+(?:of\s+)?)?" + NAME_LINE + r"(?:\s*,|\s+located|\s+situated|\n|$)",
            text,
        )

    def _extract_fire_safety(self, text: str) -> dict[str, Any]:
        return {
            "certificate_number": _search(r"(?:Certificate|NOC|Ref|Licence)\s*(?:No|Number|#)\.?[:\s]*([A-Za-z0-9/\-_]{4,})", text),
            "valid_until": _search(r"(?:Valid\s*(?:Up\s*to|Upto|Until|till|thru|through)|Expiry\s*Date|Date\s*of\s*Expiry)[:\s.]*" + DATE_PATTERN, text),
            "issue_date": _search(r"(?:Date\s*of\s*Issue|Issued\s*on|Issue\s*Date)[:\s.]*" + DATE_PATTERN, text),
            "holder": self._holder(text),
            "issuing_authority": _search(r"(?:Issued\s*by|Office\s*of\s*the)[:\s.]*([^\n\r]+)", text),
        }

    def _extract_audit_report(self, text: str) -> dict[str, Any]:
        income = _search(r"(?:Total\s*(?:Income|Receipts|Revenue)|Gross\s*Income)[:\s₹Rs.]*([\d,]+(?:\.\d{2})?)", text)
        expense = _search(r"(?:Total\s*(?:Expenditure|Expenses)|Gross\s*Expenses)[:\s₹Rs.]*([\d,]+(?:\.\d{2})?)", text)
        return {
            "financial_year": _search(r"(?:Financial\s*Year|F\.?Y\.?)[:\s.]*(\d{4}\s*[-–]\s*\d{2,4})", text),
            # ICAI UDIN: 2-digit year + 6-digit membership no + 10 alphanumerics
            "udin": _search(r"UDIN[:\s]*([0-9]{8}[A-Z0-9]{10})\b", text) or _search(r"\b([0-9]{8}[A-Z]{2}[A-Z0-9]{8})\b", text, 0),
            "ca_membership_no": _search(r"(?:Membership\s*(?:No|Number)|M\.?\s?No)\.?[:\s]*(\d{5,8})", text),
            "client_name": _search(r"(?:To the (?:Governing Body|Members|Trustees) of)\s+" + NAME_LINE + r"(?:\n|$|,)", text),
            "total_income": income.replace(",", "") if income else None,
            "total_expenditure": expense.replace(",", "") if expense else None,
        }

    def _extract_land_document(self, text: str) -> dict[str, Any]:
        data: dict[str, Any] = {
            "deed_number": _search(r"(?:Document|Deed|Registration)\s*(?:No|Number)\.?[:\s]*([A-Za-z0-9/\-_]{4,})", text),
            "survey_numbers": _search(r"(?:Survey\s*No|Khasra\s*No)\.?[:\s]*([0-9][0-9A-Za-z,/\- ]*)", text),
            "owner": _search(r"(?:in favour of|Registered\s+owner|Purchaser)[:\s]+" + NAME_LINE + r"(?:\.|\n|$|,)", text),
        }
        m = re.search(r"(\d+(?:\.\d+)?)\s*(Acres?|Hectares?|Sq\.?\s*(?:Meters|Metres|m))\b", text, re.IGNORECASE)
        if m:
            value, unit = float(m.group(1)), m.group(2).lower()
            acres = value if unit.startswith("acre") else value * 2.47105 if unit.startswith("hect") else value / 4046.86
            data["land_area"] = m.group(0)
            data["land_area_acres"] = round(acres, 2)
        return data

    def _extract_faculty_list(self, text: str) -> dict[str, Any]:
        def stated(label: str) -> int | None:
            v = _search(rf"(?<!Associate )(?<!Assistant ){label}s?\s*[:\-]\s*(\d+)", text)
            return int(v) if v else None

        prof = stated("Professor")
        assoc = stated("Associate Professor")
        asst = stated("Assistant Professor")
        if prof is None and assoc is None and asst is None:
            # Fall back to counting rows that carry a designation
            assoc = len(re.findall(r"\bAssociate\s+Professor\b", text, re.IGNORECASE))
            asst = len(re.findall(r"\bAssistant\s+Professor\b", text, re.IGNORECASE))
            prof = max(len(re.findall(r"\bProfessor\b", text, re.IGNORECASE)) - assoc - asst, 0)
        prof, assoc, asst = prof or 0, assoc or 0, asst or 0
        return {
            "professors_count": prof,
            "associate_professors_count": assoc,
            "assistant_professors_count": asst,
            "total_faculty": prof + assoc + asst,
            "phd_qualified_count": len(re.findall(r"\bPh\.?\s?D\b", text, re.IGNORECASE)),
            "institution_name": _search(r"^\s*" + NAME_LINE + r"\s+[—-]\s+(?:APPROVED\s+)?FACULTY", text, re.IGNORECASE | re.MULTILINE),
            "faculty_members": self._faculty_rows(text),
        }

    @staticmethod
    def _faculty_rows(text: str) -> list[dict[str, Any]]:
        """One record per faculty row that carries a PAN (identity key for the collusion graph)."""
        rows = []
        for line in text.splitlines():
            pan = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", line)
            if not pan:
                continue
            designation = re.search(r"\b(Associate Professor|Assistant Professor|Professor)\b", line)
            name = line[: designation.start()].strip(" |,-") if designation else line[: pan.start()].strip(" |,-")
            fid = re.search(r"\b(FAC-\d{4,}|\d-\d{9,10})\b", line)
            bio = re.search(r"\b(BIO-[A-Z0-9]{6,})\b", line)
            rows.append({"name": name[:80], "designation": designation.group(1) if designation else None,
                         "pan": pan.group(1), "faculty_id": fid.group(1) if fid else None,
                         "biometric_ref": bio.group(1) if bio else None})
        return rows

    @staticmethod
    def _extract_asset_register(text: str) -> dict[str, Any]:
        items = []
        for line in text.splitlines():
            sn = re.search(r"(?:S/?N|Serial\s*No\.?)\s*[:#]\s*((?=[A-Z0-9\-]*\d)[A-Z0-9][A-Z0-9\-]{4,})", line, re.IGNORECASE)
            if sn:
                items.append({"description": line[: sn.start()].strip(" |,-:")[:80], "serial": sn.group(1).upper()})
        return {"equipment": items, "equipment_count": len(items)}

    def _extract_affidavit(self, text: str) -> dict[str, Any]:
        return {
            "stamp_certificate_no": _search(r"(?:Stamp\s*Certificate\s*No|Certificate\s*No|Stamp\s*No|GRN)\.?[:\s]*([A-Za-z0-9/\-_]{6,})", text),
            "notary_name": _search(r"(?:Notary\s*Public|Advocate\s*&\s*Notary)[:\s.]*([^\n\r,]+)", text),
            "deponent_institution": _search(r"(?:on behalf of|Secretary of|Principal of)\s+" + NAME_LINE + r"(?:,|\n|$)", text),
            "verified_date": _search(r"(?:Verified at [A-Za-z ]+ on|Dated)[:\s]*" + DATE_PATTERN, text),
        }

    def _extract_building_plan(self, text: str) -> dict[str, Any]:
        area = _search(r"(?:Built[- ]?up\s*Area|Total\s*Built[- ]?up|Total\s*Area)[:\s.]*([\d,]+(?:\.\d+)?)\s*(?:Sq\.?\s*M)", text)
        rooms = [
            {"room": r.strip(), "area_sqm": float(a)}
            for r, a in re.findall(r"(Classroom[\w\- ]*?)[:\s]+(\d+(?:\.\d+)?)\s*(?:sq\.?\s*m|m2|sqm)", text, re.IGNORECASE)
        ]
        dims = []
        for room, area_s, l_s, w_s in re.findall(
                r"(Classroom[\w\- ]*?)[:\s]+(\d+(?:\.\d+)?)\s*(?:sq\.?\s*m|m2|sqm)\s*\(\s*(\d+(?:\.\d+)?)\s*m?\s*[x×]\s*(\d+(?:\.\d+)?)\s*m?\s*\)",
                text, re.IGNORECASE):
            dims.append({"room": room.strip(), "stated_sqm": float(area_s), "length_m": float(l_s), "width_m": float(w_s)})
        floors = _search(r"Floors?[:\s]+G\s*\+\s*(\d+)", text)
        coverage = _search(r"(?:Ground\s*Coverage|Footprint)[:\s.]*([\d,]+(?:\.\d+)?)\s*(?:Sq\.?\s*M)", text)
        return {
            "room_dimensions": dims,
            "floors": int(floors) + 1 if floors else None,
            "ground_coverage_sqm": _num(coverage),
            "approval_number": _search(r"(?:Approval|Sanction|Plan)\s*(?:No|Number)\.?[:\s]*([A-Za-z0-9/\-_]{4,})", text),
            "built_up_area_sqm": _num(area),
            "sanctioning_authority": _search(r"(?:Approved\s*by|Sanctioned\s*by)[:\s.]*([^\n\r,]+)", text),
            "classrooms": rooms,
            "classroom_count": len(rooms) or None,
            "min_classroom_area_sqm": min(r["area_sqm"] for r in rooms) if rooms else None,
        }

    def _extract_noc(self, text: str) -> dict[str, Any]:
        return {
            "noc_number": _search(r"(?:NOC\s*No|Letter\s*No|Ref\s*No)\.?[:\s]*([A-Za-z0-9/\-_]{4,})", text),
            "valid_until": _search(r"(?:Valid\s*(?:Up\s*to|Upto|Until|till)|Validity)[:\s.]*" + DATE_PATTERN, text),
            "issue_date": _search(r"(?:Date\s*of\s*Issue|Dated)[:\s.]*" + DATE_PATTERN, text),
            "university": _search(r"(" + r"[A-Z][A-Za-z.&,'\- ]{3,120}?University" + r")", text, 0),
            "holder": self._holder(text),
        }


data_extractor = DataExtractor()
