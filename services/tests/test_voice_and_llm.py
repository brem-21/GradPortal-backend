import pytest

from shared.errors import UpstreamError
from shared.llm import extract_json
from voice_service.elevenlabs import strip_for_speech


class TestStripForSpeech:
    def test_removes_citation_markers(self):
        assert "[1]" not in strip_for_speech("Your CV lists Spark [1] and Airflow [2].")

    def test_removes_markdown_emphasis_and_bullets(self):
        out = strip_for_speech("**Strong** points:\n- `Spark`\n- Airflow")
        assert "*" not in out and "`" not in out and "- " not in out

    def test_collapses_newlines_into_sentences(self):
        out = strip_for_speech("First point.\n\nSecond point.")
        assert "\n" not in out
        assert "First point" in out and "Second point" in out

    def test_leaves_plain_prose_alone(self):
        text = "Your statement names three supervisors but gives a reason for only one."
        assert strip_for_speech(text) == text


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
