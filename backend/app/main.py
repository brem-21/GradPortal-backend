import logging
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.crypto import cipher
from app.core.db import engine

logging.basicConfig(level=logging.INFO, format="%(message)s")
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
        if settings.environment == "development"
        else structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger(__name__)

app = FastAPI(
    title=settings.project_name,
    version="0.1.0",
    description=(
        "Graduate opportunity portal: ingestion agent, opportunity search, contact "
        "outreach from the user's own mailbox, mentorship and notifications."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)

# Admin-uploaded background media and story photographs. Served read-only and
# unauthenticated: the landing page shows these to signed-out visitors.
Path(settings.media_storage_dir).mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_storage_dir), name="media")


@app.on_event("startup")
def on_startup() -> None:
    if not cipher.enabled:
        log.warning(
            "token_encryption_disabled",
            hint="Set TOKEN_ENCRYPTION_KEY or outreach mailbox connection will be refused.",
        )
    if settings.auth_jwt_secret == "change-me-to-a-long-random-string":
        log.warning("default_auth_secret_in_use", hint="Set AUTH_JWT_SECRET before deploying.")


@app.get("/health", tags=["meta"])
def health() -> dict:
    checks = {"api": "ok"}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
    checks["token_encryption"] = "configured" if cipher.enabled else "missing"
    healthy = all(v in {"ok", "configured"} for v in checks.values())
    return {"status": "healthy" if healthy else "degraded", "checks": checks}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
