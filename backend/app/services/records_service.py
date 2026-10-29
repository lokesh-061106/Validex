"""Access to institutional records held in authorized AICTE systems (through the connector adapter)."""

import logging
from typing import Any

from app.models.application import Application
from app.services.connectors import get_connector
from app.mock_authority.service import SourceUnavailable

logger = logging.getLogger(__name__)


class RecordsService:
    def fetch(self, app: Application) -> tuple[dict[str, Any] | None, str]:
        """Return (record, status) where status is found | not_found | no_permanent_id | unavailable."""
        if not app.permanent_id:
            return None, "no_permanent_id"
        try:
            rec = get_connector().institution_record(app.permanent_id)
        except SourceUnavailable as e:
            logger.warning(f"AICTE records unavailable: {e}")
            return None, "unavailable"
        return (rec, "found") if rec else (None, "not_found")


records_service = RecordsService()
