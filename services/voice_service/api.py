from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel

from shared.auth import Principal, build_auth_dependency
from voice_service import elevenlabs
from voice_service.config import settings

principal_dep = build_auth_dependency(settings)
router = APIRouter(prefix="/voice", tags=["voice"])


class TranscriptRead(BaseModel):
    text: str
    language: str | None
    duration_seconds: float | None


@router.post("/transcribe", response_model=TranscriptRead)
async def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    _: Principal = Depends(principal_dep),
) -> TranscriptRead:
    """Speech to text. The caller then sends the text to rag-service as a normal turn."""
    data = await file.read()
    transcript = await elevenlabs.transcribe(
        data,
        filename=file.filename or "audio.webm",
        content_type=file.content_type or "audio/webm",
        language=language,
    )
    return TranscriptRead(
        text=transcript.text,
        language=transcript.language,
        duration_seconds=transcript.duration_seconds,
    )
