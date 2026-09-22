import eval_service.models  # noqa: F401
from eval_service.config import SCHEMA, settings
from eval_service.db import Base
from shared.alembic_env import run

run(Base.metadata, SCHEMA, settings.database_url)
