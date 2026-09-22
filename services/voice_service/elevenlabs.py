"""ElevenLabs speech-to-text and text-to-speech.

Stateless by design: this service holds the vendor key and nothing else, so it
can be scaled, rate-limited or replaced without touching conversation state.
"""

import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
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

# Citation markers belong in the transcript, not in the audio.
CITATION_MARKER = re.compile(r"\[\d+\]")
MARKDOWN_NOISE = re.compile(r"[*_`#>]|^\s*[-•]\s*", re.MULTILINE)


@dataclass
class Transcript:
    text: str
    language: str | None = None
    duration_seconds: float | None = None
    words: list[dict] = field(default_factory=list)


def _headers() -> dict[str, str]:
    if not settings.elevenlabs_api_key:
        raise ProviderNotConfigured(
            "ELEVENLABS_API_KEY is not set, so speech input and spoken replies are "
            "unavailable. Add it to services/.env and restart."
        )
    return {"xi-api-key": settings.elevenlabs_api_key}


def strip_for_speech(text: str) -> str:
    """Make written text speakable.

    Markdown read aloud is unbearable, and '[1]' becomes 'bracket one'.
    """
    cleaned = CITATION_MARKER.sub("", text)
    cleaned = MARKDOWN_NOISE.sub("", cleaned)
    cleaned = re.sub(r"\n{2,}", ". ", cleaned)
    cleaned = re.sub(r"\n", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\.\s*\.", ".", cleaned)
    return cleaned.strip()


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
    duration = None
    if words:
        last = words[-1]
        duration = last.get("end")

    return Transcript(
        text=text,
        language=payload.get("language_code"),
        duration_seconds=duration,
        words=words[:500],
    )


async def synthesise(
    text: str, voice_id: str | None = None, model_id: str | None = None
) -> tuple[AsyncIterator[bytes], Callable[[], Awaitable[None]]]:
    """Open a validated TTS stream.

    The upstream status is checked *before* anything is returned, because a
    StreamingResponse commits 200 and its headers the moment it starts — an
    error raised inside the generator after that point reaches the browser as
    an empty 200, which is indistinguishable from silence. Returning the
    iterator only once the upstream has accepted the request means a rejection
    (a plan restriction, a bad voice id) still surfaces as a real error code.

    Returns (chunks, aclose). The caller must await aclose() when finished.
    """
    speakable = strip_for_speech(text)
    if not speakable:
        raise ValidationError("There is nothing to speak.")
    if len(speakable) > settings.max_tts_characters:
        speakable = speakable[: settings.max_tts_characters].rsplit(" ", 1)[0] + "\u2026"

    voice = voice_id or settings.elevenlabs_voice_id
    url = f"{settings.elevenlabs_base_url}/text-to-speech/{voice}/stream"
    payload = {
        "text": speakable,
        "model_id": model_id or settings.elevenlabs_tts_model,
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }

    client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0))
    try:
        request = client.build_request(
            "POST", url, headers={**_headers(), "Accept": "audio/mpeg"}, json=payload
        )
        response = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise UpstreamError(f"Text-to-speech request failed: {exc}") from exc
    except Exception:
        await client.aclose()
        raise

    if response.status_code >= 400:
        body = (await response.aread()).decode()[:400]
        await response.aclose()
        await client.aclose()
        detail = body
        try:
            parsed = json.loads(body).get("detail")
            if isinstance(parsed, dict):
                detail = parsed.get("message") or parsed.get("status") or body
            elif isinstance(parsed, str):
                detail = parsed
        except (ValueError, AttributeError):
            pass

        if response.status_code in (401, 403):
            raise ProviderNotConfigured(f"ElevenLabs rejected the API key: {detail}")
        if response.status_code == 402:
            raise ProviderNotConfigured(
                "ElevenLabs will not synthesise speech on this plan: "
                f"{detail} Spoken replies need a paid plan, or a voice from your own "
                "VoiceLab rather than a library voice."
            )
        raise UpstreamError(
            f"ElevenLabs text-to-speech returned {response.status_code}: {detail}"
        )

    async def close() -> None:
        await response.aclose()
        await client.aclose()

    return response.aiter_bytes(), close


async def list_voices() -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{settings.elevenlabs_base_url}/voices", headers=_headers()
            )
    except httpx.HTTPError as exc:
        raise UpstreamError(f"Could not list voices: {exc}") from exc

    if response.status_code >= 400:
        raise UpstreamError(f"ElevenLabs returned {response.status_code}")

    return [
        {
            "voice_id": voice.get("voice_id"),
            "name": voice.get("name"),
            "category": voice.get("category"),
            "preview_url": voice.get("preview_url"),
            "labels": voice.get("labels", {}),
        }
        for voice in response.json().get("voices", [])
    ]
