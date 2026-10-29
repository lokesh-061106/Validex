"""Document intake and the processing pipeline.

Intake validates the file (never trusting the client's filename or MIME type), stamps it with the
chain-of-custody watermark and only then stores it. Processing recovers the original bytes from the
stored object, checks them against the custody hash, and runs:
    OCR -> classify -> extract fields -> locate fields -> forensics -> duplicates -> source verification
Lab photos / videos go to computer vision, campus boundaries to spatial verification, and faculty
lists / asset registers also feed the collusion graph. Stages are recorded for officers only.
Processing runs on a Celery worker when USE_CELERY is set, otherwise as a background task.
"""

import base64
import hashlib
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

import fitz
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import storage
from app.ml.data_extractor import data_extractor
from app.ml.document_classifier import classifier
from app.ml.forgery_detector import forgery_detector
from app.ml.image_hash import phash
from app.ml.infrastructure_cv import infrastructure_cv
from app.ml.ocr_engine import ocr_engine
from app.models.application import Application
from app.models.document import Document, DocumentStatus, DocumentType
from app.services import custody_service
from app.services.audit_service import audit_service

logger = logging.getLogger(__name__)

ALLOWED = {
    "pdf": ("application/pdf", lambda b: b[:5] == b"%PDF-"),
    "jpeg": ("image/jpeg", lambda b: b[:3] == b"\xff\xd8\xff"),
    "png": ("image/png", lambda b: b[:8] == b"\x89PNG\r\n\x1a\n"),
    "mp4": ("video/mp4", lambda b: b[4:8] == b"ftyp"),
    "geojson": ("application/geo+json", lambda b: b.lstrip()[:1] == b"{" and b'"type"' in b[:4096]),
}
CV_TYPES = {DocumentType.LAB_PHOTO}
ID_FIELDS = ("certificate_number", "udin", "deed_number", "noc_number", "stamp_certificate_no", "approval_number")


def sniff(file_bytes: bytes) -> tuple[str, str]:
    for kind, (mime, test) in ALLOWED.items():
        if test(file_bytes):
            return kind, mime
    raise HTTPException(status_code=415, detail="Unsupported file type. Upload PDF, JPEG, PNG, MP4 or GeoJSON.")


class CustodyBreach(RuntimeError):
    pass


def safe_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._\- ]+", "_", name).strip() or "upload"
    return name[:120]


def _save_data_uri(object_name: str, data_uri: str | None) -> bool:
    if not data_uri:
        return False
    storage.upload_bytes(base64.b64decode(data_uri.split(",", 1)[1]), object_name, "image/jpeg")
    return True


def evidence_object(doc: Document, kind: str) -> str:
    return f"{doc.storage_path}.{kind}.jpg"


class DocumentService:
    def create_document(self, db: Session, app: Application, file_bytes: bytes, filename: str,
                        user_id: uuid.UUID | None, doc_type: DocumentType | None = None,
                        replaces: Document | None = None) -> Document:
        if len(file_bytes) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        if len(file_bytes) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_MB} MB")
        kind, mime = sniff(file_bytes)
        filename = safe_filename(filename)
        if kind == "mp4":
            doc_type = DocumentType.LAB_PHOTO

        if kind == "geojson":
            doc_type = DocumentType.CAMPUS_BOUNDARY

        doc_id = uuid.uuid4()
        received_at = datetime.now(timezone.utc)
        manifest = custody_service.build_manifest(file_bytes, kind, doc_id, app.id, user_id, received_at)
        try:
            stored, stored_mime = custody_service.apply(file_bytes, kind, manifest)
        except custody_service.CustodyError as e:
            raise HTTPException(status_code=422, detail=str(e))
        storage_path = f"applications/{app.id}/{doc_id}"
        # Only the watermarked object is ever written to storage
        storage.upload_bytes(stored, storage_path, stored_mime)
        doc = Document(
            id=doc_id, application_id=app.id, doc_type=doc_type or (replaces.doc_type if replaces else DocumentType.OTHER),
            original_filename=filename, storage_path=storage_path, file_size=len(file_bytes), mime_type=stored_mime,
            content_hash=manifest["original_sha256"], status=DocumentStatus.PENDING,
            extracted_data={"classification": {"source": "manual" if doc_type else "pending"}},
            custody={**manifest, "stored_sha256": hashlib.sha256(stored).hexdigest(), "stored_size": len(stored),
                     "original_mime": mime},
            processing_stage="queued", processing_progress=0, uploaded_by=user_id, is_current=True,
        )
        db.add(doc)
        if replaces is not None:
            replaces.is_current = False
            replaces.superseded_by_id = doc_id
        db.commit()
        db.refresh(doc)
        audit_service.log_event(
            db=db, action="DOCUMENT_REPLACED" if replaces else "DOCUMENT_UPLOADED", user_id=user_id, application_id=app.id,
            details={"document_id": str(doc.id), "filename": filename, "sha256": doc.content_hash, "size": doc.file_size,
                     "stored_sha256": doc.custody["stored_sha256"], "watermark": manifest["watermark"],
                     "declared_type": doc_type.value if doc_type else None,
                     "replaces": str(replaces.id) if replaces else None},
        )
        return doc

    @staticmethod
    def original_bytes(doc: Document) -> bytes:
        """The bytes exactly as the institution submitted them, recovered from the watermarked object.

        Raises CustodyBreach if the stored object no longer yields the original recorded at intake."""
        stored = storage.get_bytes(doc.storage_path)
        if not doc.custody:  # legacy document stored before watermarking
            return stored
        original, embedded = custody_service.extract(stored, doc.custody.get("kind", ""))
        if original is None or hashlib.sha256(original).hexdigest() != doc.content_hash:
            raise CustodyBreach(f"Stored object for {doc.id} does not yield the original recorded at intake")
        return original

    @staticmethod
    def _stage(db: Session, doc: Document, stage: str, progress: int) -> None:
        doc.processing_stage, doc.processing_progress = stage, progress
        db.commit()

    def process_document(self, db: Session, doc_id: uuid.UUID, user_id: uuid.UUID | None = None) -> Document:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None:
            raise ValueError("Document not found")
        started = datetime.now(timezone.utc)
        try:
            try:
                file_bytes = self.original_bytes(doc)
            except CustodyBreach as e:
                doc.status = DocumentStatus.FAILED
                doc.processing_stage = "custody_breach"
                db.commit()
                audit_service.log_event(db=db, action="CUSTODY_BREACH", application_id=doc.application_id,
                                        details={"document_id": str(doc.id), "error": str(e)})
                return doc
            doc.status = DocumentStatus.PROCESSING
            if doc.doc_type in CV_TYPES:
                self._process_visual_evidence(db, doc, file_bytes)
            elif doc.doc_type == DocumentType.CAMPUS_BOUNDARY:
                self._process_boundary(db, doc, file_bytes)
            else:
                self._process_document_file(db, doc, file_bytes)
            if doc.doc_type in (DocumentType.FACULTY_LIST, DocumentType.ASSET_REGISTER):
                from app.services.graph_service import graph_service
                graph_service.ingest_document(db, doc)
            self._stage(db, doc, "duplicates", 85)
            from app.services.duplicate_service import find_duplicates
            data = dict(doc.extracted_data or {})
            data["duplicates"] = find_duplicates(db, doc)
            doc.extracted_data = data
            db.commit()

            from app.services.verification_service import verification_service
            if doc.doc_type not in CV_TYPES and doc.doc_type != DocumentType.CAMPUS_BOUNDARY:
                self._stage(db, doc, "source_verification", 92)
                verification_service.verify_document(db, doc.id, user_id=user_id, file_bytes=file_bytes)

            data = dict(doc.extracted_data or {})
            data["processing_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
            doc.extracted_data = data
            suspected = (data.get("forensics") or {}).get("is_suspected")
            doc.status = DocumentStatus.FLAGGED if suspected or data.get("duplicates") else DocumentStatus.VALIDATED
            self._stage(db, doc, "done", 100)
        except Exception as e:
            logger.exception(f"Processing failed for {doc_id}: {e}")
            db.rollback()
            doc = db.query(Document).filter(Document.id == doc_id).first()
            doc.status = DocumentStatus.FAILED
            doc.processing_stage = f"failed: {type(e).__name__}"
            db.commit()
        audit_service.log_event(
            db=db, action="DOCUMENT_PROCESSED", application_id=doc.application_id,
            details={"document_id": str(doc.id), "type": doc.doc_type.value, "status": doc.status.value,
                     "ocr_engine": (doc.extracted_data or {}).get("ocr", {}).get("engine"),
                     "forgery_level": (doc.extracted_data or {}).get("forgery_level"),
                     "duplicates": len((doc.extracted_data or {}).get("duplicates") or [])},
        )
        return doc

    def _process_document_file(self, db: Session, doc: Document, file_bytes: bytes) -> None:
        is_pdf = file_bytes[:5] == b"%PDF-"
        self._stage(db, doc, "ocr", 15)
        ocr = ocr_engine.extract(file_bytes, is_pdf)

        self._stage(db, doc, "classification", 35)
        detected, score = classifier.classify_text_only(ocr.text)
        declared_manually = (doc.extracted_data or {}).get("classification", {}).get("source") == "manual"
        classification: dict[str, Any] = {"source": "manual" if declared_manually else "auto", "detected": detected.value, "score": score}
        if not declared_manually:
            doc.doc_type = classifier.classify(ocr.text, doc.original_filename)
        elif detected not in (DocumentType.OTHER, doc.doc_type):
            classification["mismatch"] = (f"Uploaded as '{doc.doc_type.value}' but the content reads like "
                                          f"'{detected.value}'. It may have been placed in the wrong checklist slot.")

        self._stage(db, doc, "extraction", 50)
        fields = data_extractor.extract_fields(ocr.text, doc.doc_type)
        from app.services.graph_service import pseudonymise_faculty, scrub_text
        if fields.get("faculty_members"):
            fields["faculty_members"] = pseudonymise_faculty(fields["faculty_members"])
        if ocr.engine != "pdf-native":
            from app.services.matching import ocr_fix_identifier
            for key in ID_FIELDS:
                if fields.get(key):
                    repaired = ocr_fix_identifier(fields[key])
                    if repaired != fields[key]:
                        fields[f"{key}_ocr_raw"], fields[key] = fields[key], repaired
        data: dict[str, Any] = {
            **fields,
            "classification": classification,
            "ocr": {"engine": ocr.engine, "confidence": ocr.confidence, "page_count": ocr.page_count},
            "ocr_confidence": ocr.confidence,
            "raw_text_snippet": scrub_text(ocr.text[:1500]),
            "field_locations": self._locate_fields(file_bytes, is_pdf, fields, ocr.words),
        }
        doc.page_count = max(ocr.page_count, 1)
        if not is_pdf:
            doc.phash = phash(file_bytes)

        self._stage(db, doc, "forensics", 70)
        report = forgery_detector.analyze_document(file_bytes, doc.original_filename)
        data["forensics"] = report.to_dict()
        data["forgery_score"] = report.forgery_score
        data["forgery_level"] = report.level
        data["has_evidence_image"] = _save_data_uri(evidence_object(doc, "evidence"), report.evidence_image)
        data["has_ela_heatmap"] = _save_data_uri(evidence_object(doc, "ela"), report.heatmap)
        doc.extracted_data = data
        db.commit()

    def _process_boundary(self, db: Session, doc: Document, file_bytes: bytes) -> None:
        from app.services.spatial_service import spatial_service

        self._stage(db, doc, "spatial_verification", 40)
        app = db.query(Application).filter(Application.id == doc.application_id).first()
        doc.extracted_data = {"classification": {"source": "manual", "detected": "campus_boundary"},
                              "spatial": spatial_service.analyze_boundary(db, app, file_bytes)}
        db.commit()

    def _process_visual_evidence(self, db: Session, doc: Document, file_bytes: bytes) -> None:
        from app.services.compliance_service import compliance_service
        from app.services.rule_engine import infra_norms

        self._stage(db, doc, "computer_vision", 30)
        app = db.query(Application).filter(Application.id == doc.application_id).first()
        norms = infra_norms(compliance_service.active_rules(db), app)
        report = infrastructure_cv.analyze(file_bytes, norms, doc.original_filename)
        result = report.to_dict()
        annotated = result.pop("annotated_image_base64", None)
        data: dict[str, Any] = {
            "classification": {"source": "manual", "detected": "lab_photo"},
            "infrastructure": result,
            "has_annotated_image": _save_data_uri(evidence_object(doc, "annotated"), annotated),
        }
        if not infrastructure_cv.is_video(file_bytes, doc.original_filename):
            doc.phash = phash(file_bytes)
            self._stage(db, doc, "forensics", 60)
            report_f = forgery_detector.analyze_document(file_bytes, doc.original_filename)
            data["forensics"] = report_f.to_dict()
            data["forgery_score"] = report_f.forgery_score
            data["forgery_level"] = report_f.level
            data["has_evidence_image"] = _save_data_uri(evidence_object(doc, "evidence"), report_f.evidence_image)
        doc.extracted_data = data
        db.commit()

    @staticmethod
    def _locate_fields(file_bytes: bytes, is_pdf: bool, fields: dict[str, Any], words: list[dict]) -> dict[str, Any]:
        """Bounding boxes (normalised 0..1) of extracted values, so the UI can point at the evidence."""
        targets = {k: str(v) for k, v in fields.items()
                   if isinstance(v, (str, int, float)) and not k.endswith("_iso") and 2 < len(str(v)) < 80}
        out: dict[str, Any] = {}
        if is_pdf:
            try:
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                for key, value in targets.items():
                    for pno, page in enumerate(list(doc)[:5]):
                        hits = page.search_for(value)
                        if hits:
                            r, w, h = hits[0], page.rect.width, page.rect.height
                            out[key] = {"page": pno, "x": r.x0 / w, "y": r.y0 / h, "w": r.width / w, "h": r.height / h}
                            break
            except Exception:
                pass
        if words and len(out) < len(targets):
            # Raster OCR: match on the first token of the value
            for key, value in targets.items():
                if key in out:
                    continue
                first = value.split()[0].lower()
                for wd in words:
                    if first and first in wd["text"].lower():
                        x0, y0, x1, y1 = wd["bbox"]
                        out[key] = {"page": wd.get("page", 0), "bbox_px": [x0, y0, x1, y1]}
                        break
        return out

    def schedule_processing(self, db: Session, doc_id: uuid.UUID, user_id: uuid.UUID | None, background_tasks=None) -> str:
        if settings.USE_CELERY:
            from app.tasks.document_tasks import process_document_task
            process_document_task.delay(str(doc_id), str(user_id) if user_id else None)
            return "celery"
        if background_tasks is not None and not settings.INLINE_PROCESSING:
            background_tasks.add_task(run_processing_in_new_session, doc_id, user_id)
            return "background"
        self.process_document(db, doc_id, user_id)
        return "inline"


# Bounds peak memory on small hosts: heavy documents are processed this many at a time
_processing_slots = threading.BoundedSemaphore(max(settings.MAX_CONCURRENT_PROCESSING, 1))


def run_processing_in_new_session(doc_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    from app.core.database import SessionLocal

    with _processing_slots:
        db = SessionLocal()
        try:
            document_service.process_document(db, doc_id, user_id)
        finally:
            db.close()


document_service = DocumentService()
