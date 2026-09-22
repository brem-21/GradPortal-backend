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


class OpenRouterSettings(BaseServiceSettings):
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = "openai/gpt-4o-mini"
    openrouter_reasoning_model: str = "openai/o4-mini"
    openrouter_app_name: str = "GradPortal"
    openrouter_site_url: str = "http://localhost:3000"


class EmbeddingSettings(OpenRouterSettings):
    """Embeddings, served through OpenRouter.

    OpenRouter exposes POST /api/v1/embeddings even though no embedding model
    appears in its /models catalogue — which is why this looked unsupported.
    Using it means one provider key for the whole system instead of two, and
    no uploaded CV is sent anywhere the chat calls do not already go.

    `openai_api_key` remains as an optional override for anyone who would
    rather bill embeddings to OpenAI directly.
    """

    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dimensions: int = 1536
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    @property
    def embeddings_use_openai_directly(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def embeddings_base_url(self) -> str:
        return self.openai_base_url if self.openai_api_key else self.openrouter_base_url

    @property
    def embeddings_api_key(self) -> str:
        return self.openai_api_key or self.openrouter_api_key

    @property
    def embeddings_model_id(self) -> str:
        # OpenAI's own API does not accept the "openai/" provider prefix.
        if self.openai_api_key:
            return self.embedding_model.removeprefix("openai/")
        return self.embedding_model


@lru_cache
def cached(settings_class: type) -> object:
    return settings_class()
