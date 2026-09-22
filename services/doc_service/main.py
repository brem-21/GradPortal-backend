from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from doc_service.api import internal_router, router
from doc_service.config import settings
from doc_service.db import engine, ensure_schema
from doc_service.service import embeddings
from shared.errors import install_error_handlers
from shared.logging import configure_logging

configure_logging(settings.service_name, settings.is_development)

app = FastAPI(
    title="GradPortal · Document Service",
    version="0.1.0",
    description=(
        "Owns uploaded application documents: parsing, chunking, embedding and "
        "vector retrieval. The only service that talks to the embedding provider."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

install_error_handlers(app, settings.service_name)
app.include_router(router)
app.include_router(internal_router)


@app.on_event("startup")
def on_startup() -> None:
    ensure_schema()


@app.get("/health", tags=["meta"])
def health() -> dict:
    checks: dict[str, str] = {"api": "ok"}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            has_vector = connection.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).first()
        checks["database"] = "ok"
        checks["pgvector"] = "ok" if has_vector else "missing"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
    checks["embeddings"] = "configured" if embeddings.configured else "missing OPENAI_API_KEY"
    checks["internal_token"] = "configured" if settings.internal_service_token else "missing"

    degraded = [key for key, value in checks.items() if value not in {"ok", "configured"}]
    return {
        "service": settings.service_name,
        "status": "healthy" if not degraded else "degraded",
        "checks": checks,
    }
