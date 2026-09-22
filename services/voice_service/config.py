from functools import lru_cache

from shared.config import BaseServiceSettings


class VoiceSettings(BaseServiceSettings):
    """Speech-to-text only.

    Text-to-speech was removed: ElevenLabs refuses library voices on the free
    tier, and a "Listen" control that can only ever error is worse than no
    control at all. Transcription works on every plan.
    """

    service_name: str = "voice-service"
    port: int = 8004

    elevenlabs_api_key: str = ""
    elevenlabs_base_url: str = "https://api.elevenlabs.io/v1"
    elevenlabs_stt_model: str = "scribe_v1"

    max_audio_bytes: int = 25 * 1024 * 1024


@lru_cache
def get_settings() -> VoiceSettings:
    return VoiceSettings()


settings = get_settings()
