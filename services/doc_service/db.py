from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase

from doc_service.config import SCHEMA, settings
from shared.db import build_get_db, make_engine, make_session_factory

engine = make_engine(settings.database_url, SCHEMA)
SessionLocal = make_session_factory(engine)


class Base(DeclarativeBase):
    __table_args__ = {"schema": SCHEMA}


get_db = build_get_db(SessionLocal)


def ensure_schema() -> None:
    """Create this service's schema and the pgvector extension if absent.

    Kept idempotent so a fresh clone boots without a manual psql step; Alembic
    still owns the tables themselves.
    """
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
