"""Audit ledger service: append-only, hash-chained log of automated checks and human actions."""

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core import request_context
from app.models.audit_log import AuditLog

_chain_lock = threading.Lock()
GENESIS = "0" * 64


def _ts(dt: datetime) -> str:
    """Timezone-normalised timestamp (SQLite drops tzinfo on reload)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="microseconds")


def compute_entry_hash(log: AuditLog) -> str:
    payload = {
        "id": str(log.id),
        "user_id": str(log.user_id) if log.user_id else None,
        "actor_role": log.actor_role,
        "application_id": str(log.application_id) if log.application_id else None,
        "action": log.action,
        "details": log.details or {},
        "ip_address": log.ip_address,
        "created_at": _ts(log.created_at),
        "prev_hash": log.prev_hash,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditService:
    @staticmethod
    def log_event(
        db: Session,
        action: str,
        user_id: uuid.UUID | None = None,
        application_id: uuid.UUID | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        actor_role: str | None = None,
    ) -> AuditLog:
        """Append an entry to the ledger, chained to the previous entry's hash."""
        clean_details = json.loads(json.dumps(details or {}, default=str))
        with _chain_lock:
            last = db.query(AuditLog.entry_hash).order_by(AuditLog.created_at.desc()).first()
            log = AuditLog(
                id=uuid.uuid4(),
                user_id=user_id,
                actor_role=actor_role or (request_context.actor_role.get() if user_id else "system"),
                application_id=application_id,
                action=action,
                details=clean_details,
                ip_address=ip_address or request_context.client_ip.get(),
                created_at=datetime.now(timezone.utc),
                prev_hash=(last[0] if last and last[0] else GENESIS),
            )
            log.entry_hash = compute_entry_hash(log)
            db.add(log)
            db.commit()
            db.refresh(log)
        return log

    @staticmethod
    def get_application_logs(db: Session, application_id: uuid.UUID, limit: int = 200) -> list[AuditLog]:
        return (
            db.query(AuditLog)
            .filter(AuditLog.application_id == application_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_recent_activity(db: Session, limit: int = 20) -> list[AuditLog]:
        return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()

    @staticmethod
    def verify_chain(db: Session) -> dict[str, Any]:
        """Recompute every entry hash and check the links. Detects edited, deleted or inserted rows."""
        logs = db.query(AuditLog).order_by(AuditLog.created_at.asc()).all()
        chained = [l for l in logs if l.entry_hash]
        legacy = len(logs) - len(chained)
        known_hashes = {l.entry_hash for l in chained}
        seen_prev: set[str] = set()
        problems: list[dict[str, Any]] = []
        for l in chained:
            if compute_entry_hash(l) != l.entry_hash:
                problems.append({"id": str(l.id), "action": l.action, "problem": "entry content was modified"})
            if l.prev_hash != GENESIS and l.prev_hash not in known_hashes:
                problems.append({"id": str(l.id), "action": l.action, "problem": "previous entry is missing (deleted)"})
            if l.prev_hash in seen_prev:
                problems.append({"id": str(l.id), "action": l.action, "problem": "chain fork (entry inserted out of order)"})
            seen_prev.add(l.prev_hash)
        return {
            "valid": not problems,
            "entries_checked": len(chained),
            "legacy_unchained_entries": legacy,
            "problems": problems[:50],
            "head_hash": chained[-1].entry_hash if chained else None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


audit_service = AuditService()
