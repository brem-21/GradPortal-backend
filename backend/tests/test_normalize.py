from datetime import date

from app.agent.normalize import (
    classify_degrees,
    classify_fields,
    classify_funding,
    classify_type,
    clean_text,
    content_hash,
    detect_international,
    extract_deadline,
)
from app.core.enums import DegreeLevel, FieldOfStudy, FundingType, OpportunityType


class TestClassifyFields:
    def test_detects_ai_from_synonyms(self):
        assert FieldOfStudy.ARTIFICIAL_INTELLIGENCE in classify_fields(
            "PhD in Deep Learning for Computer Vision"
        )

    def test_detects_multiple_fields(self):
        found = classify_fields("MSc Data Science and Computer Science")
        assert FieldOfStudy.DATA_SCIENCE in found
        assert FieldOfStudy.COMPUTER_SCIENCE in found

    def test_out_of_scope_returns_empty(self):
        assert classify_fields("Fellowship in Renaissance Poetry") == []

    def test_bare_analytics_is_dropped_next_to_a_stronger_signal(self):
        # "analytics" alone is noisy; a real data-analytics phrase keeps it.
        found = classify_fields("Machine learning research using analytics tooling")
        assert FieldOfStudy.DATA_ANALYTICS not in found
        assert FieldOfStudy.DATA_ANALYTICS in classify_fields("Business intelligence graduate role")


class TestClassifyType:
    def test_scholarship_beats_program_when_both_appear(self):
        assert (
            classify_type("PhD Scholarship in Computer Science") == OpportunityType.SCHOLARSHIP
        )

    def test_assistantship(self):
        assert classify_type("Graduate Teaching Assistant") == OpportunityType.ASSISTANTSHIP

    def test_falls_back_to_default(self):
        assert classify_type("Something unlabelled") == OpportunityType.GRADUATE_PROGRAM


class TestClassifyDegrees:
    def test_phd_and_masters(self):
        found = classify_degrees("Open to MSc and PhD candidates")
        assert DegreeLevel.PHD in found
        assert DegreeLevel.MASTERS in found


class TestClassifyFunding:
    def test_fully_funded(self):
        assert classify_funding("This is a fully-funded studentship") == FundingType.FULLY_FUNDED

    def test_unknown_when_silent(self):
        assert classify_funding("A great opportunity") == FundingType.UNKNOWN


class TestInternational:
    def test_positive(self):
        assert detect_international("Open to international students") is True

    def test_negative_wins(self):
        assert detect_international("US citizens only; international students welcome") is False

    def test_unknown(self):
        assert detect_international("Apply before the deadline") is None


class TestDeadline:
    def test_labelled_long_form(self):
        parsed, label = extract_deadline("Application deadline: 15 January 2027")
        assert parsed == date(2027, 1, 15)
        assert label

    def test_us_format_trims_trailing_words(self):
        parsed, label = extract_deadline("Deadline: September 30, 2026 Applications are open")
        assert parsed == date(2026, 9, 30)
        assert label == "September 30, 2026"

    def test_rolling(self):
        assert extract_deadline("Applications are reviewed on a rolling basis") == (None, "Rolling")

    def test_absent(self):
        assert extract_deadline("No dates mentioned here") == (None, None)


class TestCleanText:
    def test_decodes_entities_and_collapses_space(self):
        assert clean_text("Arts &#38;  Technology\n\nFellowship") == "Arts & Technology Fellowship"

    def test_double_encoded(self):
        assert clean_text("R&amp;amp;D") == "R&D"

    def test_truncates_on_word_boundary(self):
        out = clean_text("alpha beta gamma delta epsilon", limit=16)
        assert out.endswith("…")
        assert len(out) <= 16


class TestContentHash:
    def test_stable_across_cosmetic_differences(self):
        a = content_hash("PhD in AI", "https://x.edu/phd/", "MIT")
        b = content_hash("  phd in ai ", "https://X.edu/phd?utm_source=rss", "mit")
        assert a == b

    def test_differs_by_organization(self):
        assert content_hash("PhD in AI", "https://x.edu/a", "MIT") != content_hash(
            "PhD in AI", "https://x.edu/a", "Stanford"
        )


class TestRealCatalogueTitles:
    """Regressions from crawling real university course catalogues.

    Every title here was produced by an actual crawl of Edinburgh, KTH or EPFL
    and misclassified before the pattern it exercises was added.
    """

    def test_law_degrees_are_not_artificial_intelligence(self):
        # "LLM" is Master of Laws far more often than Large Language Model in
        # a course catalogue; the bare abbreviation used to match.
        for title in (
            "European Law LLM",
            "Commercial Law LLM",
            "Information Technology Law (Online Learning) LLM",
            "Comparative Private Law LLM",
        ):
            assert classify_fields(title) == [], title

    def test_large_language_models_still_classify(self):
        assert FieldOfStudy.ARTIFICIAL_INTELLIGENCE in classify_fields(
            "Large Language Models and Generative AI"
        )

    def test_finance_degrees_are_not_data_analytics(self):
        # Bare "analytics" used to catch these.
        for title in (
            "Banking Innovation and Risk Analytics MSc",
            "Accounting and Financial Management MSc",
        ):
            assert classify_fields(title) == [], title

    def test_qualified_analytics_still_classifies(self):
        assert FieldOfStudy.DATA_ANALYTICS in classify_fields("Business Analytics MSc")

    def test_two_word_cyber_security(self):
        assert FieldOfStudy.COMPUTER_SCIENCE in classify_fields(
            "Cyber Security, Privacy and Trust MSc"
        )
        assert FieldOfStudy.COMPUTER_SCIENCE in classify_fields("Cybersecurity")

    def test_catalogue_spellings_of_computing(self):
        for title in (
            "Computing Science MSc",
            "Advanced Computing MSc",
            "Software Systems MSc",
            "Computational Science and Engineering",
        ):
            assert FieldOfStudy.COMPUTER_SCIENCE in classify_fields(title), title

    def test_unrelated_degrees_stay_out(self):
        for title in (
            "Advanced Chemical Engineering MSc",
            "Acoustics and Music Technology MSc",
            "Architecture",
            "Civil Engineering",
            "Veterinary Science",
            "History of Art",
        ):
            assert classify_fields(title) == [], title


class TestTitleFirstClassification:
    def test_page_boilerplate_does_not_override_a_clear_title(self):
        from app.agent.normalize import classify_fields_titled

        # A law programme page mentioning "data" in its blurb must not become
        # a data science listing.
        assert (
            classify_fields_titled(
                "European Law LLM",
                "Our graduates work with data protection regimes and machine learning policy.",
            )
            == []
        )

    def test_body_is_consulted_when_the_title_says_nothing(self):
        from app.agent.normalize import classify_fields_titled

        assert FieldOfStudy.DATA_SCIENCE in classify_fields_titled(
            "Programme P-4471",
            "A taught masters in data science and statistical learning.",
        )
