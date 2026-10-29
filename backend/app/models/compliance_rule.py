"""SQLAlchemy ComplianceRule model for configurable AICTE norms."""

import uuid
from datetime import datetime, timezone
import enum
from sqlalchemy import Column, String, Boolean, Integer, DateTime, Enum, JSON, Uuid

from app.core.database import Base
from app.models.validation_result import Severity


class RuleCategory(str, enum.Enum):
    INFRASTRUCTURE = "infrastructure"
    ACADEMIC = "academic"
    FINANCIAL = "financial"
    STATUTORY = "statutory"
    SAFETY = "safety"


class ComplianceRule(Base):
    """A data-driven rule. `conditions` is interpreted by services/rule_engine.py."""

    __tablename__ = "compliance_rules"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_code = Column(String(64), unique=True, index=True, nullable=False)
    title = Column(String(255), nullable=False)
    category = Column(Enum(RuleCategory), default=RuleCategory.STATUTORY, nullable=False)
    description = Column(String(1000), nullable=False)
    conditions = Column(JSON, default=dict, nullable=False)
    # Application categories this rule applies to; empty list = all categories
    applies_to = Column(JSON, default=list, nullable=True)
    severity = Column(Enum(Severity), default=Severity.CRITICAL, nullable=True)
    handbook_reference = Column(String(255), nullable=True)
    version = Column(Integer, default=1, server_default="1", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
