import pytest

from shared.errors import UpstreamError
from shared.llm import extract_json


class TestExtractJson:
    def test_plain_object(self):
        assert extract_json('{"verdict": "borderline"}')["verdict"] == "borderline"

    def test_fenced_block(self):
        assert extract_json('```json\n{"score": 4}\n```')["score"] == 4

    def test_object_wrapped_in_prose(self):
        # Reasoning models routinely narrate before answering.
        text = 'Here is my assessment:\n{"score": 3, "severity": "major"}\nHope that helps.'
        assert extract_json(text)["severity"] == "major"

    def test_raises_when_there_is_no_json(self):
        with pytest.raises(UpstreamError, match="did not return JSON"):
            extract_json("I could not complete this review.")


class TestAudioAcceptance:
    """Speech-to-text is the only ElevenLabs feature that remains."""

    def test_accepts_what_browsers_actually_record(self):
        from voice_service.elevenlabs import ACCEPTED_AUDIO

        # Chrome's MediaRecorder emits webm (sometimes labelled video/webm),
        # Safari emits mp4.
        for content_type in ("audio/webm", "video/webm", "audio/mp4", "audio/mpeg"):
            assert content_type in ACCEPTED_AUDIO, content_type

    def test_text_to_speech_is_gone(self):
        import voice_service.elevenlabs as module

        # It was removed rather than disabled: a "Listen" control that can only
        # error on the free tier is worse than no control.
        assert not hasattr(module, "synthesise")
        assert not hasattr(module, "list_voices")
