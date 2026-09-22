from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from shared.auth import Principal, build_auth_dependency
from voice_service import elevenlabs
from voice_service.config import settings

principal_dep = build_auth_dependency(settings)
router = APIRouter(prefix="/voice", tags=["voice"])


class TranscriptRead(BaseModel):
    text: str
    language: str | None
    duration_seconds: float | None


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    voice_id: str | None = None


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


@router.post("/speak")
async def speak(payload: SpeakRequest, _: Principal = Depends(principal_dep)) -> StreamingResponse:
    """Text to speech, streamed so playback can start before generation finishes.

    The upstream call is validated before this returns, so a rejection reaches
    the caller as a real status code rather than an empty 200.
    """
    chunks, close = await elevenlabs.synthesise(payload.text, payload.voice_id)

    async def body():
        try:
            async for chunk in chunks:
                yield chunk
        finally:
            await close()

    return StreamingResponse(
        body(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"}
    )


@router.get("/voices")
async def voices(_: Principal = Depends(principal_dep)) -> dict:
    return {"voices": await elevenlabs.list_voices(), "default": settings.elevenlabs_voice_id}
