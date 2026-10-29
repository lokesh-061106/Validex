"""SQLAlchemy database engine and session configuration."""

import logging

from sqlalchemy import Enum as SAEnum, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

is_sqlite = db_url.startswith("sqlite")
engine_kwargs = {"echo": False}
if not is_sqlite:
    engine_kwargs.update({"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20})
else:
    engine_kwargs.update({"connect_args": {"check_same_thread": False}})

engine = create_engine(db_url, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


def get_db():
    """FastAPI dependency — yields a database session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def sync_schema(bind=None):
    """Create missing tables and add columns / enum values introduced after the DB was created.

    A lightweight stand-in for migrations so an existing prototype database keeps working.
    It only ever adds; it never drops or alters existing columns.
    """
    bind = bind or engine
    import app.models  # noqa: F401  (register all models)

    Base.metadata.create_all(bind=bind)
    insp = inspect(bind)
    dialect = bind.dialect
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                coltype = col.type.compile(dialect=dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
                if col.server_default is not None:
                    default = col.server_default.arg
                    default_sql = (
                        str(default.compile(dialect=dialect)) if hasattr(default, "compile") else f"'{default}'"
                    )
                    ddl += f" DEFAULT {default_sql}"
                conn.execute(text(ddl))
                logger.info(f"Schema sync: added column {table.name}.{col.name}")

    if dialect.name == "postgresql":
        # The audit ledger must not be rewritten by cascading deletes: drop the legacy FK on
        # audit_logs.application_id (the one deliberate non-additive change).
        with bind.begin() as conn:
            for fk in insp.get_foreign_keys("audit_logs"):
                if fk.get("constrained_columns") == ["application_id"] and fk.get("name"):
                    conn.execute(text(f'ALTER TABLE audit_logs DROP CONSTRAINT "{fk["name"]}"'))
                    logger.info(f"Schema sync: dropped {fk['name']} from audit_logs")
        # New enum members must be added to the native PG enum types
        with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for table in Base.metadata.sorted_tables:
                for col in table.columns:
                    if isinstance(col.type, SAEnum) and col.type.native_enum and col.type.name:
                        for name in col.type.enums:
                            conn.execute(text(f"ALTER TYPE {col.type.name} ADD VALUE IF NOT EXISTS '{name}'"))
