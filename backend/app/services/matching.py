"""Field normalisation and fuzzy matching with explainable, field-level results."""

import re
from datetime import date
from typing import Any

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from app.ml.dates import parse_date

ABBREVIATIONS = {
    r"\binst\.?\b": "institute",
    r"\binstt\.?\b": "institute",
    r"\btech\.?\b": "technology",
    r"\bengg\.?\b": "engineering",
    r"\bengr\.?\b": "engineering",
    r"\bcoll\.?\b": "college",
    r"\bst\.?\b": "saint",
    r"\buniv\.?\b": "university",
    r"\bmgmt\.?\b": "management",
    r"\bsci\.?\b": "science",
    r"&": " and ",
}
STOPWORDS = {"the", "of", "and", "m/s", "ms"}


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    s = value.lower()
    for pattern, repl in ABBREVIATIONS.items():
        s = re.sub(pattern, repl, s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(w for w in s.split() if w not in STOPWORDS)


def name_similarity(a: str | None, b: str | None) -> float:
    """0-100 similarity combining token-set ratio and Jaro-Winkler on normalised names."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    token = fuzz.token_set_ratio(na, nb)
    jw = JaroWinkler.similarity(na, nb) * 100
    return round(max(token, jw * 0.95), 1)


OCR_DIGIT_CONFUSIONS = str.maketrans({"O": "0", "o": "0", "D": "0", "I": "1", "l": "1", "|": "1", "Z": "2", "z": "2",
                                       "S": "5", "s": "5", "B": "8", "G": "6"})


def ocr_fix_identifier(value: str | None) -> str | None:
    """Repair common OCR look-alike errors inside digit-dominated segments of an identifier
    (e.g. '2OZO' -> '2020'), leaving alphabetic segments such as 'NOC' or 'DFS' unchanged."""
    if not value:
        return value
    confusable = set("OoDIl|ZzSsBG")

    def repair(m: re.Match) -> str:
        run, start, end = m.group(0), m.start(), m.end()
        touches_digit = (start > 0 and value[start - 1].isdigit()) or (end < len(value) and value[end].isdigit())
        if touches_digit and len(run) <= 4 and all(c in confusable for c in run):
            return run.translate(OCR_DIGIT_CONFUSIONS)
        return run

    return re.sub(r"[A-Za-z|]+", repair, value)


def identifier_distance(a: str | None, b: str | None) -> int:
    from rapidfuzz.distance import Levenshtein
    return Levenshtein.distance(normalize_identifier(a), normalize_identifier(b))


def normalize_identifier(value: str | None) -> str:
    return re.sub(r"[\s\-_/.]", "", (value or "").upper())


def compare_field(field: str, submitted: Any, official: Any, kind: str = "text", threshold: float = 88.0) -> dict[str, Any]:
    """Compare one field and explain the outcome."""
    row: dict[str, Any] = {"field": field, "submitted": submitted, "official": official, "kind": kind}
    if submitted in (None, "") :
        row.update(match=None, score=None, reason="Not found in the submitted document (OCR)")
        return row
    if official in (None, ""):
        row.update(match=None, score=None, reason="Not available from the official source")
        return row

    if kind == "name":
        score = name_similarity(str(submitted), str(official))
        row.update(score=score, match=score >= threshold,
                   reason=f"Name similarity {score:.0f}% (threshold {threshold:.0f}%) after normalising abbreviations")
    elif kind == "identifier":
        same = normalize_identifier(str(submitted)) == normalize_identifier(str(official))
        row.update(score=100.0 if same else 0.0, match=same,
                   reason="Identifiers match exactly" if same else "Identifiers differ")
    elif kind == "date":
        d1 = submitted if isinstance(submitted, date) else parse_date(str(submitted))
        d2 = official if isinstance(official, date) else parse_date(str(official))
        if d1 is None or d2 is None:
            row.update(match=None, score=None, reason="Date could not be parsed")
        else:
            row.update(score=100.0 if d1 == d2 else 0.0, match=d1 == d2,
                       submitted=d1.isoformat(), official=d2.isoformat(),
                       reason="Dates match" if d1 == d2 else f"Date differs by {abs((d1 - d2).days)} days")
    elif kind == "number":
        try:
            n1, n2 = float(submitted), float(official)
            tol = max(abs(n2) * 0.02, 0.01)
            ok = abs(n1 - n2) <= tol
            row.update(score=100.0 if ok else 0.0, match=ok,
                       reason="Values match (±2%)" if ok else f"Values differ ({n1:g} vs {n2:g})")
        except (TypeError, ValueError):
            row.update(match=None, score=None, reason="Not a number")
    else:
        score = float(fuzz.ratio(str(submitted).lower().strip(), str(official).lower().strip()))
        row.update(score=score, match=score >= threshold, reason=f"Text similarity {score:.0f}%")
    return row
