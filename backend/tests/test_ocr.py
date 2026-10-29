"""Unit tests for OCR classification and structured field extraction."""

from app.models.document import DocumentType
from app.ml.document_classifier import classifier
from app.ml.data_extractor import data_extractor


def test_document_classification_fire_safety():
    sample_text = """
    GOVERNMENT OF NCT OF DELHI
    DIRECTORATE OF FIRE SERVICES
    No Objection Certificate (Fire Safety)
    This is to certify that building was inspected by Fire Officer...
    """
    doc_type = classifier.classify(sample_text, "fire_noc_2024.pdf")
    assert doc_type == DocumentType.FIRE_SAFETY


def test_document_classification_audit_report():
    sample_text = """
    INDEPENDENT AUDITOR'S REPORT
    To the members of the Governing Body
    UDIN: 24054321BK89123490
    Chartered Accountants Balance Sheet and Profit and Loss statement.
    """
    doc_type = classifier.classify(sample_text, "audit_statement.pdf")
    assert doc_type == DocumentType.AUDIT_REPORT


def test_data_extraction_fire_safety():
    sample_text = """
    Certificate No: FS-NOC-99214
    Valid Up to: 31/12/2026
    Date of Issue: 10/01/2024
    Issued by: Delhi Fire Services Department
    """
    data = data_extractor.extract_fields(sample_text, DocumentType.FIRE_SAFETY)
    assert data["certificate_number"] == "FS-NOC-99214"
    assert data["valid_until"] == "31/12/2026"
    assert data["issue_date"] == "10/01/2024"


def test_data_extraction_audit_report():
    sample_text = """
    Financial Year: 2024-2025
    UDIN: 24054321BK89123490
    Membership No: 054321
    Total Income: ₹ 12,50,000
    Total Expenditure: ₹ 10,20,000
    """
    data = data_extractor.extract_fields(sample_text, DocumentType.AUDIT_REPORT)
    assert data["financial_year"] == "2024-2025"
    assert data["udin"] == "24054321BK89123490"
    assert data["ca_membership_no"] == "054321"
    assert data["total_income"] == "1250000"
