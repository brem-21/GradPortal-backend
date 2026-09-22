from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from eval_service.agent import llm
from eval_service.api import router
from eval_service.config import settings
from eval_service.db import engine, ensure_schema
from shared.errors import install_error_handlers
from shared.logging import configure_logging

configure_logging(settings.service_name, settings.is_development)

app = FastAPI(
    title="GradPortal · Evaluation Service",
    version="0.1.0",
    description=(
        "Reviews application documents as a graduate admissions committee would, "
        "against master's or doctoral rubrics."
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
    checks["reasoning_model"] = settings.openrouter_reasoning_model

    degraded = [
        key
        for key, value in checks.items()
        if key not in {"reasoning_model"} and value not in {"ok", "configured"}
    ]
    return {
        "service": settings.service_name,
        "status": "healthy" if not degraded else "degraded",
        "checks": checks,
    }
