from functools import lru_cache

from shared.config import BaseServiceSettings


class VoiceSettings(BaseServiceSettings):
    service_name: str = "voice-service"
    port: int = 8004

    elevenlabs_api_key: str = ""
    elevenlabs_base_url: str = "https://api.elevenlabs.io/v1"
    elevenlabs_stt_model: str = "scribe_v1"
    # Turbo: the latency difference is what makes a spoken reply feel like a
    # conversation rather than a download.
    elevenlabs_tts_model: str = "eleven_turbo_v2_5"
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    max_audio_bytes: int = 25 * 1024 * 1024
    max_tts_characters: int = 2500


@lru_cache
def get_settings() -> VoiceSettings:
    return VoiceSettings()


settings = get_settings()
