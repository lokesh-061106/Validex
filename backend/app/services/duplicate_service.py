"""Duplicate and re-use detection across all applications.

* exact duplicates: identical SHA-256 of the file
* near-duplicate images: perceptual hash within a Hamming distance (same lab photo resubmitted,
  resized or recompressed, possibly by another institution)
* identifier re-use: the same certificate / UDIN / deed number submitted by different institutions
Matches are flagged for review, never auto-rejected.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.ml.image_hash import hamming
from app.models.application import Application
from app.models.document import Document, DocumentType
from app.services.matching import normalize_identifier
from app.services.verification_service import SOURCES

PHASH_THRESHOLD = 8


def find_duplicates(db: Session, doc: Document) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    others = (
        db.query(Document, Application)
        .join(Application, Document.application_id == Application.id)
        .filter(Document.id != doc.id, Document.is_current.is_(True))
        .all()
    )
    id_field = SOURCES.get(doc.doc_type, {}).get("id_field")
    my_id = normalize_identifier((doc.extracted_data or {}).get(id_field)) if id_field else ""

    mine = db.get(Application, doc.application_id)
    for other, app in others:
        same_app = other.application_id == doc.application_id
        if not same_app and mine and app.institution_id == mine.institution_id:
            continue  # an institution re-using its own file across its own applications (e.g. renewals) is legitimate
        info = {"document_id": str(other.id), "filename": other.original_filename, "application_id": str(app.id),
                "application_number": app.application_number, "institution_name": app.institution_name,
                "same_application": same_app}
        if doc.content_hash and other.content_hash == doc.content_hash:
            matches.append({**info, "match": "exact_file", "reason": "Byte-identical file"})
            continue
        if doc.phash and other.phash and doc.doc_type == DocumentType.LAB_PHOTO and other.doc_type == DocumentType.LAB_PHOTO:
            dist = hamming(doc.phash, other.phash)
            if dist <= PHASH_THRESHOLD:
                matches.append({**info, "match": "near_duplicate_image", "distance": dist,
                                "reason": f"Visually near-identical photo (pHash distance {dist}/64)"})
                continue
        if my_id and other.doc_type == doc.doc_type and not same_app:
            other_id = normalize_identifier((other.extracted_data or {}).get(id_field))
            if other_id and other_id == my_id:
                matches.append({**info, "match": "identifier_reuse", "identifier": (doc.extracted_data or {}).get(id_field),
                                "reason": f"Same {id_field.replace('_', ' ')} submitted by another institution"})
    return matches
