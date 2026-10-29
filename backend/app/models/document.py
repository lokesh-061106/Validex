"""SQLAlchemy Document model for storing uploaded evidence."""

import uuid
from datetime import datetime, timezone
import enum
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Enum, ForeignKey, JSON, Uuid, true
from sqlalchemy.orm import relationship

from app.core.database import Base


class DocumentType(str, enum.Enum):
    FIRE_SAFETY = "fire_safety"
    AUDIT_REPORT = "audit_report"
    LAND_DOCUMENT = "land_document"
    FACULTY_LIST = "faculty_list"
    NOC = "noc"
    AFFIDAVIT = "affidavit"
    BUILDING_PLAN = "building_plan"
    LAB_PHOTO = "lab_photo"
    ASSET_REGISTER = "asset_register"      # equipment list with serial numbers
    CAMPUS_BOUNDARY = "campus_boundary"    # GeoJSON polygon of the campus (and building footprints)
    OTHER = "other"


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    VALIDATED = "validated"
    FLAGGED = "flagged"
    REJECTED = "rejected"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id = Column(Uuid, ForeignKey("applications.id"), nullable=False)
    doc_type = Column(Enum(DocumentType), default=DocumentType.OTHER, nullable=False)
    original_filename = Column(String(255), nullable=False)
    storage_path = Column(String(512), nullable=False)
    file_size = Column(Integer, default=0, nullable=False)
    mime_type = Column(String(128), default="application/pdf", nullable=False)
    content_hash = Column(String(64), nullable=True, index=True)  # SHA-256 (exact duplicates)
    phash = Column(String(16), nullable=True, index=True)  # 64-bit perceptual hash (near duplicates)
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False)
    extracted_data = Column(JSON, default=dict, nullable=False)
    page_count = Column(Integer, default=1, nullable=False)
    processing_stage = Column(String(64), nullable=True)
    processing_progress = Column(Integer, default=0, nullable=True)
    # Versioning for rectification: a replaced document is kept but marked not current
    is_current = Column(Boolean, default=True, server_default=true(), nullable=False)
    superseded_by_id = Column(Uuid, nullable=True)
    uploaded_by = Column(Uuid, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    files_purged_at = Column(DateTime(timezone=True), nullable=True)
    # Signed chain-of-custody manifest (original SHA-256/size, receive time, watermark) + stored-object hash
    custody = Column(JSON, nullable=True)

    application = relationship("Application", back_populates="documents")
    validation_results = relationship("ValidationResult", back_populates="document", cascade="all, delete-orphan")
    verifications = relationship("Verification", back_populates="document", cascade="all, delete-orphan")
