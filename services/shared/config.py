"""Settings shared by every service.

Each service subclasses BaseServiceSettings and adds only what it needs, so a
misconfigured key fails at that service's startup rather than silently at the
first request.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    environment: str = "development"

    # Auth — the same HS256 secret Auth.js signs with.
    auth_jwt_secret: str = ""
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_issuer: str = "gradportal-web"
    auth_jwt_audience: str = "gradportal-api"

    # Service-to-service bearer for /internal endpoints.
    internal_service_token: str = ""

    database_url: str = "postgresql+psycopg://gradportal:gradportal@localhost:5437/gradportal"

    core_api_url: str = "http://localhost:8000"
    doc_service_url: str = "http://localhost:8001"
    rag_service_url: str = "http://localhost:8002"
    eval_service_url: str = "http://localhost:8003"
    voice_service_url: str = "http://localhost:8004"
    frontend_origin: str = "http://localhost:3000"

    @property
    def allowed_origins(self) -> list[str]:
        return [self.frontend_origin]

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


class OpenAISettings(BaseServiceSettings):
    """Embeddings only. OpenRouter does not expose an embeddings endpoint, which
    is why a second provider key exists at all."""

    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536


class OpenRouterSettings(BaseServiceSettings):
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = "anthropic/claude-sonnet-4.5"
    openrouter_reasoning_model: str = "deepseek/deepseek-r1"
    openrouter_app_name: str = "GradPortal"
    openrouter_site_url: str = "http://localhost:3000"


@lru_cache
def cached(settings_class: type) -> object:
    return settings_class()
