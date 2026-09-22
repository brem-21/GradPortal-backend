import rag_service.models  # noqa: F401
from rag_service.config import SCHEMA, settings
from rag_service.db import Base
from shared.alembic_env import run

run(Base.metadata, SCHEMA, settings.database_url)
