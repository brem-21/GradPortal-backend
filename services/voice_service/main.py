from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.errors import install_error_handlers
from shared.logging import configure_logging
from voice_service.api import router
from voice_service.config import settings

configure_logging(settings.service_name, settings.is_development)

app = FastAPI(
    title="GradPortal · Voice Service",
    version="0.1.0",
    description=(
        "ElevenLabs speech-to-text. Stateless: it holds the vendor key and "
        "never touches conversation or document data."
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


@app.get("/health", tags=["meta"])
def health() -> dict:
    configured = bool(settings.elevenlabs_api_key)
    return {
        "service": settings.service_name,
        "status": "healthy" if configured else "degraded",
        "checks": {
            "api": "ok",
            "elevenlabs": "configured" if configured else "missing ELEVENLABS_API_KEY",
        },
        "models": {"stt": settings.elevenlabs_stt_model},
    }
