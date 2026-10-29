"""Aggregated API router combining all domain endpoints."""

from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.applications import router as applications_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.compliance import router as compliance_router
from app.api.dashboard import router as dashboard_router
from app.api.documents import router as documents_router
from app.api.infrastructure import router as infrastructure_router
from app.api.notifications import router as notifications_router
from app.api.validation import router as validation_router
from app.api.verification import router as verification_router
from app.api.triage import router as triage_router
from app.api.deadlines import router as deadlines_router
from app.api.workflow import router as workflow_router

api_router = APIRouter(prefix="/api")

for r in (auth_router, applications_router, documents_router, validation_router, verification_router,
          compliance_router, infrastructure_router, dashboard_router, audit_router, notifications_router, admin_router,
          triage_router, deadlines_router, workflow_router):
    api_router.include_router(r)

__all__ = ["api_router"]
