from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    frontend_origin: str = "http://localhost:3000"
    project_name: str = "GradPortal API"

    # Database
    database_url: str = "postgresql+psycopg://gradportal:gradportal@localhost:5437/gradportal"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth — the shared secret Auth.js signs session JWTs with.
    auth_jwt_secret: str = "change-me-to-a-long-random-string"
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_issuer: str = "gradportal-web"
    auth_jwt_audience: str = "gradportal-api"

    # Encryption for OAuth refresh tokens at rest
    token_encryption_key: str = ""

    # Google / Microsoft (send-as-user)
    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_tenant_id: str = "common"

    # Platform notification email
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    notification_from_email: str = "notifications@gradportal.local"
    notification_from_name: str = "GradPortal"

    # Ingestion agent
    agent_user_agent: str = "GradPortalBot/0.1 (+https://gradportal.local/bot)"
    agent_request_timeout: int = 20
    agent_max_concurrency: int = 5
    agent_respect_robots: bool = True

    # Gated source credentials
    linkedin_partner_access_token: str = ""
    handshake_api_token: str = ""
    handshake_institution_id: str = ""

    # Admin-uploaded background media and story photographs.
    media_storage_dir: str = "./.media"
    max_media_upload_bytes: int = 25 * 1024 * 1024

    cors_origins: list[str] = Field(default_factory=list)

    @property
    def allowed_origins(self) -> list[str]:
        return self.cors_origins or [self.frontend_origin]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
