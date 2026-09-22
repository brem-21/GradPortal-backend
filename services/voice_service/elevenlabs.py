"""ElevenLabs speech-to-text.

Stateless by design: this service holds the vendor key and nothing else, so it
can be scaled, rate-limited or replaced without touching conversation state.
"""

from dataclasses import dataclass, field

import httpx
import structlog

from shared.errors import ProviderNotConfigured, UpstreamError, ValidationError
from voice_service.config import settings

log = structlog.get_logger(__name__)

ACCEPTED_AUDIO = {
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/m4a",
    "audio/x-m4a",
    "video/webm",  # MediaRecorder on Chrome labels webm audio this way
}


@dataclass
class Transcript:
    text: str
    language: str | None = None
    duration_seconds: float | None = None
    words: list[dict] = field(default_factory=list)


def _headers() -> dict[str, str]:
    if not settings.elevenlabs_api_key:
        raise ProviderNotConfigured(
            "ELEVENLABS_API_KEY is not set, so speech input is unavailable. "
            "Add it to services/.env and restart."
        )
    return {"xi-api-key": settings.elevenlabs_api_key}


async def transcribe(
    data: bytes, filename: str, content_type: str, language: str | None = None
) -> Transcript:
    if not data:
        raise ValidationError("No audio was received.")
    if len(data) > settings.max_audio_bytes:
        limit = settings.max_audio_bytes // (1024 * 1024)
        raise ValidationError(f"That recording is larger than the {limit}MB limit.")
    if content_type and content_type.split(";")[0] not in ACCEPTED_AUDIO:
        log.info("unusual_audio_type", content_type=content_type)

    form: dict[str, str] = {"model_id": settings.elevenlabs_stt_model}
    if language:
        form["language_code"] = language

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            response = await client.post(
                f"{settings.elevenlabs_base_url}/speech-to-text",
                headers=_headers(),
                data=form,
                files={"file": (filename or "audio.webm", data, content_type or "audio/webm")},
            )
    except httpx.HTTPError as exc:
        raise UpstreamError(f"Speech-to-text request failed: {exc}") from exc

    if response.status_code >= 400:
        raise UpstreamError(
            f"ElevenLabs speech-to-text returned {response.status_code}: {response.text[:300]}"
        )

    payload = response.json()
    text = (payload.get("text") or "").strip()
    if not text:
        raise ValidationError(
            "Nothing could be transcribed from that recording. Check the microphone "
            "and try speaking again."
        )

    words = payload.get("words") or []
    duration = words[-1].get("end") if words else None

    return Transcript(
        text=text,
        language=payload.get("language_code"),
        duration_seconds=duration,
        words=words[:500],
    )
