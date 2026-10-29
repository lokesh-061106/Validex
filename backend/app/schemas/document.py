"""Pydantic schemas for document upload, metadata, and extracted data."""

from uuid import UUID
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict
from app.models.document import DocumentType, DocumentStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_id: UUID
    doc_type: DocumentType
    original_filename: str
    file_size: int
    mime_type: str
    status: DocumentStatus
    extracted_data: dict[str, Any]
    page_count: int
    processing_stage: str | None = None
    processing_progress: int | None = None
    is_current: bool = True
    superseded_by_id: UUID | None = None
    uploaded_at: datetime


class DocumentDetailResponse(DocumentResponse):
    verifications: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    versions: list[dict[str, Any]] = []
