"""Clarification requests for AMBER items (missing / expired / unreadable), encrypted to the institution.

Asymmetric by design:
  * cryptographically: content is encrypted to the institution's public key; only its browser can read it;
  * informationally: requests list only what to supply, never forensic reasons or RED anomalies,
    so institutions cannot learn how the detectors work.
The database keeps the ciphertext, non-sensitive item metadata and a hash of the plaintext.
"""

import logging
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.application import Application
from app.models.notification import Notification
from app.models.user import User
from app.models.validation_result import ValidationResult
from app.services.audit_service import audit_service
from app.services.rule_engine import AMBER
from app.services.secure_message import encrypt_for

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    if not settings.SMTP_HOST:
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.SMTP_FROM, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as s:
            s.starttls()
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        logger.warning(f"Email delivery failed: {e}")
        return False


class NotificationService:
    @staticmethod
    def clarification_candidates(db: Session, app: Application) -> list[ValidationResult]:
        return (db.query(ValidationResult)
                .filter(ValidationResult.application_id == app.id, ValidationResult.rag == AMBER,
                        ValidationResult.actionable_by == "institution").all())

    def issue_clarification(self, db: Session, app: Application, sender: User, note: str,
                            due_days: int = 7, finding_ids: list[uuid.UUID] | None = None) -> Notification:
        recipient = db.query(User).filter(User.id == app.institution_id).first()
        if not recipient or not recipient.public_key_pem:
            raise HTTPException(status_code=409, detail="The institution has not set up its secure inbox yet "
                                                        "(it is created automatically when the institution signs in).")
        findings = self.clarification_candidates(db, app)
        if finding_ids:
            wanted = {str(f) for f in finding_ids}
            findings = [f for f in findings if str(f.id) in wanted]
        if not findings:
            raise HTTPException(status_code=422, detail="No amber items to request; red findings are reviewed by officers, not sent to institutions.")

        due = datetime.now(timezone.utc) + timedelta(days=due_days)
        items, seen = [], set()
        # One request per document: the rule, the signed QR and the registry often describe the same expiry.
        # Rule findings sort first so their plain-language wording is the one kept.
        for f in sorted(findings, key=lambda f: (f.rule_code is None, f.check_type.value)):
            doc_type = f.document.doc_type.value if f.document else (f.details or {}).get("rule", {}).get("doc_type")
            key = doc_type or f.finding
            if key in seen:
                continue
            seen.add(key)
            items.append({"doc_type": doc_type, "request": f.finding.split(": ", 1)[-1] if f.rule_code else f.finding,
                          "what_to_do": f.fix_hint or "Provide the missing or current document."})
        payload = {"application_number": app.application_number, "note": note, "due": due.date().isoformat(), "items": items}
        envelope, digest = encrypt_for(recipient.public_key_pem, payload)
        n = Notification(
            application_id=app.id, recipient_id=recipient.id, sender_id=sender.id,
            subject=f"Clarification requested for application {app.application_number}",
            body="This request is end-to-end encrypted. Open it in the Validex portal to read it.",
            items=[{"fingerprint": f.fingerprint, "rule_code": f.rule_code,
                    "doc_type": f.document.doc_type.value if f.document else None} for f in findings],
            encrypted_payload=envelope, payload_sha256=digest, channels=["in_app"], due_date=due,
        )
        if send_email(recipient.email, n.subject, "You have a secure clarification request on the Validex portal."):
            n.channels = ["in_app", "email"]
        db.add(n)
        app.rectification_due = due
        db.commit()
        db.refresh(n)
        audit_service.log_event(
            db=db, action="CLARIFICATION_REQUESTED", user_id=sender.id, application_id=app.id,
            details={"notification_id": str(n.id), "items": len(findings), "due": due.isoformat(),
                     "payload_sha256": digest, "alg": envelope["alg"], "fingerprints": [f.fingerprint for f in findings]},
        )
        return n


notification_service = NotificationService()
