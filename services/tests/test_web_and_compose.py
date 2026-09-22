"""Web-search plumbing and the email-refinement prompt contract."""

import pytest

from rag_service.prompts import (
    EMAIL_REFINE,
    OPPORTUNITY_CONTEXT,
    WEB_ENABLED,
    describe_opportunity,
)
from shared.config import OpenRouterSettings
from shared.llm import OpenRouterClient


@pytest.fixture
def client() -> OpenRouterClient:
    return OpenRouterClient(OpenRouterSettings())


class TestWebSearchPayload:
    def test_plugin_absent_unless_requested(self, client: OpenRouterClient):
        payload = client._payload([], "m", 0.2, 100, False, False)
        assert "plugins" not in payload

    def test_plugin_present_when_requested(self, client: OpenRouterClient):
        payload = client._payload([], "m", 0.2, 100, False, False, web_search=True)
        assert payload["plugins"] == [{"id": "web", "max_results": 4}]

    def test_result_count_is_configurable(self, client: OpenRouterClient):
        payload = client._payload(
            [], "m", 0.2, 100, False, False, web_search=True, web_max_results=2
        )
        assert payload["plugins"][0]["max_results"] == 2


class TestCitationParsing:
    def test_extracts_url_citations(self, client: OpenRouterClient):
        citations = client._citations(
            {
                "annotations": [
                    {
                        "type": "url_citation",
                        "url_citation": {"title": "Chevening", "url": "https://chevening.org"},
                    }
                ]
            }
        )
        assert len(citations) == 1
        assert citations[0].url == "https://chevening.org"

    def test_ignores_other_annotation_types(self, client: OpenRouterClient):
        assert client._citations({"annotations": [{"type": "file", "file": {}}]}) == []

    def test_skips_entries_without_a_url(self, client: OpenRouterClient):
        assert (
            client._citations(
                {"annotations": [{"type": "url_citation", "url_citation": {"title": "x"}}]}
            )
            == []
        )

    def test_no_annotations_is_empty(self, client: OpenRouterClient):
        assert client._citations({}) == []


class TestOpportunityDescription:
    def test_includes_the_decision_relevant_fields(self):
        text = describe_opportunity(
            {
                "title": "PhD in ML",
                "organization": "ETH",
                "country": "Switzerland",
                "application_deadline": "2026-10-04",
                "fields_of_study": ["artificial_intelligence"],
                "description": "Body text here.",
            }
        )
        assert "PhD in ML" in text
        assert "ETH" in text
        assert "2026-10-04" in text
        assert "artificial intelligence" in text
        assert "Body text here." in text

    def test_omits_absent_fields_rather_than_printing_none(self):
        text = describe_opportunity({"title": "X"})
        assert "None" not in text
        assert "Deadline" not in text

    def test_truncates_a_long_description(self):
        text = describe_opportunity({"title": "X", "description": "y" * 9000})
        assert len(text) < 5000


class TestPromptGuardrails:
    def test_web_prompt_keeps_the_two_sources_separate(self):
        # The whole risk of web search here is a web claim reading as though it
        # came from the applicant's own CV.
        assert "separate" in WEB_ENABLED.lower()
        assert "never let a web claim look like" in WEB_ENABLED.lower()

    def test_opportunity_prompt_discourages_hopeless_applications(self):
        assert "not competitive" in OPPORTUNITY_CONTEXT.lower()

    def test_email_refine_forbids_inventing_credentials(self):
        lowered = EMAIL_REFINE.lower()
        assert "never add a fact about the applicant" in lowered
        assert "placeholder" in lowered

    def test_email_refine_requests_structured_output(self):
        for key in ("subject", "body", "changes", "warnings"):
            assert f'"{key}"' in EMAIL_REFINE
