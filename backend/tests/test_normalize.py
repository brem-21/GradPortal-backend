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
