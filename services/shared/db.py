"""Per-service database wiring.

Every service owns exactly one Postgres schema and never reads another's tables.
They share a physical database only because running four of them locally is not
worth the operational cost; the schema boundary is what keeps the services
independently migratable.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def make_engine(database_url: str, schema: str):
    engine = create_engine(database_url, pool_pre_ping=True, future=True)

    @event.listens_for(engine, "connect")
    def set_search_path(dbapi_connection, _record):
        # `public` stays on the path so the pgvector type resolves.
        with dbapi_connection.cursor() as cursor:
            cursor.execute(f"SET search_path TO {schema}, public")

    return engine


def make_session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def build_base(schema: str) -> type[DeclarativeBase]:
    class Base(DeclarativeBase):
        __table_args__ = {"schema": schema}

    return Base


def build_get_db(session_factory: sessionmaker):
    def get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return get_db
