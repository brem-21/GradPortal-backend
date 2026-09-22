from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from rag_service.agent import llm
from rag_service.api import router
from rag_service.config import settings
from rag_service.db import engine, ensure_schema
from shared.errors import install_error_handlers
from shared.logging import configure_logging

configure_logging(settings.service_name, settings.is_development)

app = FastAPI(
    title="GradPortal · RAG Service",
    version="0.1.0",
    description=(
        "Agentic retrieval-augmented chat over the signed-in user's own documents. "
        "Plans its own search queries, retrieves from doc-service, and answers only "
        "from what it found — with citations."
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


@app.on_event("startup")
def on_startup() -> None:
    ensure_schema()


@app.get("/health", tags=["meta"])
def health() -> dict:
    checks: dict[str, str] = {"api": "ok"}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
    checks["openrouter"] = "configured" if llm.configured else "missing OPENROUTER_API_KEY"
    checks["internal_token"] = "configured" if settings.internal_service_token else "missing"

    degraded = [key for key, value in checks.items() if value not in {"ok", "configured"}]
    return {
        "service": settings.service_name,
        "status": "healthy" if not degraded else "degraded",
        "checks": checks,
        "models": {
            "fast": settings.openrouter_default_model,
            "reasoning": settings.openrouter_reasoning_model,
        },
    }
