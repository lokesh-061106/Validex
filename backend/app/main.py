"""FastAPI application entrypoint for the AICTE validation platform (Validex)."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core import request_context
from app.core.config import settings
from app.core.database import SessionLocal, sync_schema
from app.core.security import hash_password, verify_password
from app.mock_authority.service import router as mock_authority_router
from app.models.user import User, UserRole
from app.services.compliance_service import compliance_service
from app.services.audit_service import audit_service
from app.services.workflow_service import seed_default_transitions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Demo accounts (synthetic). Seeded only outside production.
SAMPLE_USERS = [
    ("admin@aicte-india.org", "admin123", "AICTE Approval Bureau (Admin)", UserRole.ADMIN, "AICTE Headquarters, New Delhi"),
    ("scrutiny@aicte-india.org", "scrutiny123", "Regional Scrutiny Officer", UserRole.SCRUTINY, "AICTE Regional Office"),
    ("expert@aicte-india.org", "expert123", "Expert Visit Committee Member", UserRole.EXPERT, "AICTE Expert Panel"),
    ("approver@aicte-india.org", "approver123", "Application Approving Officer", UserRole.APPROVER, "AICTE Approval Bureau"),
    ("supervisor@aicte-india.org", "supervisor123", "Regional Review Supervisor", UserRole.SUPERVISOR, "AICTE Regional Office"),
    ("principal@apex.edu.in", "apex123", "Dr. S. K. Ramanathan (Principal)", UserRole.INSTITUTION, "Apex Institute of Technology & Engineering"),
    ("principal@zenith.edu.in", "zenith123", "Dr. R. Malhotra (Director)", UserRole.INSTITUTION, "Zenith College of Engineering & Research"),
    ("principal@crescent.edu.in", "crescent123", "Dr. A. Fernandes (Principal)", UserRole.INSTITUTION, "Crescent Institute of Technology"),
]


def init_db():
    sync_schema()
    db = SessionLocal()
    try:
        if not settings.is_production:
            for email, password, name, role, inst in SAMPLE_USERS:
                user = db.query(User).filter(User.email == email).first()
                if user is None:
                    db.add(User(email=email, hashed_password=hash_password(password), full_name=name, role=role, institution_name=inst))
                elif not verify_password(password, user.hashed_password):
                    # Upgrade demo accounts created with an older hashing scheme
                    user.hashed_password = hash_password(password)
            db.commit()
        else:
            bootstrap_production_admin(db)
        compliance_service.seed_default_rules(db)
        seed_default_transitions(db)
    finally:
        db.close()


def bootstrap_production_admin(db) -> bool:
    """Create the first admin only from explicitly configured credentials on an empty DB."""
    email = settings.BOOTSTRAP_ADMIN_EMAIL.strip().lower()
    password = settings.BOOTSTRAP_ADMIN_PASSWORD
    if not email and not password:
        return False
    if not email or not password:
        raise RuntimeError("Both BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD are required together")
    if "@" not in email or len(password) < 16:
        raise RuntimeError("Bootstrap email must be valid and bootstrap password must be at least 16 characters")
    if db.query(User).count() > 0:
        logger.info("Administrator bootstrap skipped because the users table is not empty")
        return False

    user = User(email=email, hashed_password=hash_password(password),
                full_name=settings.BOOTSTRAP_ADMIN_NAME.strip() or "Portal Administrator",
                role=UserRole.ADMIN, institution_name="Portal Administration")
    db.add(user)
    db.flush()
    audit_service.log_event(db=db, action="INITIAL_ADMIN_BOOTSTRAPPED", user_id=user.id,
                            actor_role="system", details={"method": "one-time deployment environment configuration"})
    logger.info("Initial administrator bootstrapped. Remove bootstrap credentials from deployment settings.")
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Validex backend...")
    init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "AI decision-support for AICTE application validation: OCR extraction, configurable checklists, "
        "tampering indicators, issuing-authority verification, infrastructure CV and a hash-chained audit ledger. "
        "All AI outputs are advisory; decisions are recorded by authorised officials."
    ),
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    forwarded = request.headers.get("x-forwarded-for")
    request_context.client_ip.set(forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None))
    request_context.actor_role.set(None)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


app.include_router(api_router)
# Simulated issuing authorities, served in-process for local demos (separate container in docker-compose)
app.include_router(mock_authority_router)


def _engines() -> dict:
    """Which ML engines are installed (checked without loading any model)."""
    import importlib.util
    import os
    import shutil
    from app.ml.detectors import ONNX_WEIGHTS

    has = lambda m: importlib.util.find_spec(m) is not None  # noqa: E731
    ocr = [n for n, ok in (("easyocr", has("easyocr")), ("tesseract", has("pytesseract") and shutil.which("tesseract"))) if ok]
    det = [n for n, ok in (("onnxruntime", has("onnxruntime") and os.path.exists(ONNX_WEIGHTS)), ("ultralytics", has("ultralytics"))) if ok]
    return {"ocr": ocr or ["pdf-text-only"], "detector": det or ["none"]}


@app.get("/health")
def health_check():
    return {"status": "healthy", "app": settings.APP_NAME, "version": "2.1.0",
            "async_mode": "celery" if settings.USE_CELERY else "background-tasks",
            "authority_connector": "http" if settings.AUTHORITY_API_URL else "in-process-mock",
            "engines": _engines(),
            "graph": _graph_backend(), "geodata_provider": settings.GEODATA_PROVIDER,
            "storage": "minio" if _storage_client() else "local-disk"}


def _graph_backend() -> str:
    from app.services.graph_service import graph_service
    return graph_service.backend


def _storage_client():
    from app.core.storage import storage
    return storage.client


@app.get("/")
def root():
    return {"message": f"Welcome to {settings.APP_NAME} API", "docs": "/docs", "health": "/health"}
