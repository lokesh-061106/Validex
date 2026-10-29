"""Keyword-based AICTE document classifier with explainable scores."""

from app.models.document import DocumentType


class DocumentClassifier:
    KEYWORDS = {
        DocumentType.FIRE_SAFETY: [
            "fire safety", "fire fighting", "fire prevention", "noc fire", "fire service",
            "no objection certificate fire", "fire station", "fire compliance", "chief fire officer", "fire noc",
        ],
        DocumentType.AUDIT_REPORT: [
            "auditor's report", "chartered accountant", "balance sheet", "profit and loss",
            "income and expenditure", "financial year", "statutory auditor", "independent auditor", "udin",
        ],
        DocumentType.LAND_DOCUMENT: [
            "sale deed", "gift deed", "lease deed", "land registration", "khasra", "khatauni",
            "survey no", "patta", "sub-registrar", "acres", "title deed",
        ],
        DocumentType.FACULTY_LIST: [
            "faculty details", "teaching staff", "assistant professor", "associate professor",
            "cadre ratio", "faculty list", "date of joining", "qualification",
        ],
        DocumentType.NOC: [
            "affiliating university", "university noc", "affiliation", "directorate of technical education",
            "board of technical education", "consent of affiliation", "no objection certificate",
        ],
        DocumentType.AFFIDAVIT: [
            "affidavit", "stamp paper", "non-judicial stamp", "notary public", "solemnly affirm",
            "deponent", "e-stamp", "before me",
        ],
        DocumentType.ASSET_REGISTER: [
            "asset register", "equipment register", "stock register", "serial no", "s/n:",
        ],
        DocumentType.BUILDING_PLAN: [
            "building plan", "approved blueprint", "municipal corporation", "development authority",
            "floor area ratio", "carpet area", "architectural drawing", "sanctioned plan", "classroom",
        ],
    }

    def scores(self, text: str, original_filename: str = "") -> dict[DocumentType, int]:
        text_lower, filename_lower = text.lower(), original_filename.lower()
        scores = {doc_type: 0 for doc_type in self.KEYWORDS}
        for doc_type, keywords in self.KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    scores[doc_type] += 2
                if kw.replace(" ", "_") in filename_lower or kw in filename_lower:
                    scores[doc_type] += 3
        return scores

    def classify(self, text: str, original_filename: str = "") -> DocumentType:
        best_type, best_score = max(self.scores(text, original_filename).items(), key=lambda x: x[1])
        return best_type if best_score >= 2 else DocumentType.OTHER

    def classify_text_only(self, text: str) -> tuple[DocumentType, int]:
        best_type, best_score = max(self.scores(text, "").items(), key=lambda x: x[1])
        return (best_type if best_score >= 4 else DocumentType.OTHER), best_score


classifier = DocumentClassifier()
