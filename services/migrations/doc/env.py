import doc_service.models  # noqa: F401  — registers tables on Base.metadata
from doc_service.config import SCHEMA, settings
from doc_service.db import Base
from shared.alembic_env import run

run(Base.metadata, SCHEMA, settings.database_url)
