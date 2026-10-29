"""Centralized application configuration using pydantic-settings."""

import logging
import os

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

DEFAULT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App
    APP_NAME: str = "Validex"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    # Deployed frontend(s); always allowed in addition to CORS_ORIGINS
    FRONTEND_ORIGINS: str = "https://validex-two.vercel.app"

    # Database (defaults to local sqlite for standalone run, overridden by .env in Docker)
    DATABASE_URL: str = "sqlite:///./validex.db"

    # Redis / Celery. When USE_CELERY is false, heavy jobs run as FastAPI background tasks.
    REDIS_URL: str = "redis://localhost:6379/0"
    USE_CELERY: bool = False
    # Process uploads synchronously inside the request (tests, seeding). Otherwise background task.
    INLINE_PROCESSING: bool = False
    # Background documents processed at once (1 keeps memory low on 512 MB hosts)
    MAX_CONCURRENT_PROCESSING: int = 1

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minio_admin"
    MINIO_SECRET_KEY: str = "minio_secret"
    MINIO_BUCKET: str = "aicte-documents"
    MINIO_SECURE: bool = False
    USE_MINIO: bool = True
    # Serve and store files strictly via MinIO (no local-disk fallback)
    REQUIRE_MINIO: bool = False

    # JWT Auth
    SECRET_KEY: str = DEFAULT_SECRET
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Uploads
    MAX_UPLOAD_MB: int = 25
    # Chain-of-custody watermark stamped on every stored file (the UTC receive time is appended)
    WATERMARK_TEXT: str = "VALIDEX - CHAIN OF CUSTODY - VERIFIED"

    # Issuing-authority connector. Empty = in-process mock adapter; otherwise base URL
    # of the mock authority service (or a real sandbox gateway).
    AUTHORITY_API_URL: str = ""
    AUTHORITY_TIMEOUT_SECONDS: float = 5.0
    # Simulate an outage of the issuing-authority source (demo of "source unavailable" + retry)
    MOCK_AUTHORITY_OUTAGE: bool = False

    # Geodata provider for observed building footprints: "simulated" (demo) or "osm" (Overpass API)
    GEODATA_PROVIDER: str = "simulated"
    OVERPASS_URL: str = "https://overpass-api.de/api/interpreter"

    # Collusion graph: Neo4j when set, otherwise an in-process graph built from PostgreSQL
    NEO4J_URI: str = ""
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # Data protection
    RETENTION_DAYS: int = 365

    # Optional SMTP for deficiency notices. If unset, notices are stored in-app only.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@validex.local"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [o.strip() for o in f"{self.CORS_ORIGINS},{self.FRONTEND_ORIGINS}".split(",") if o.strip()]
        return ["*"] if "*" in origins else list(dict.fromkeys(origins))

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
settings = Settings(_env_file=(os.path.join(BACKEND_DIR, "..", ".env"), os.path.join(BACKEND_DIR, ".env"), ".env"))

# A relative SQLite path is resolved against the backend folder, so the same DB is used whatever the cwd
if settings.DATABASE_URL.startswith("sqlite:///./"):
    settings.DATABASE_URL = "sqlite:///" + os.path.join(BACKEND_DIR, settings.DATABASE_URL[len("sqlite:///./"):]).replace("\\", "/")

if settings.SECRET_KEY == DEFAULT_SECRET:
    if settings.is_production:
        raise RuntimeError("SECRET_KEY must be set in production")
    logger.warning("Using the default development SECRET_KEY. Set SECRET_KEY before deploying.")
