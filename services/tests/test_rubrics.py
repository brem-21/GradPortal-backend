import pytest

from eval_service.prompts import committee_synthesis_prompt, document_review_prompt
from eval_service.rubrics import Track, get_rubric

KINDS = [
    "cv",
    "sop",
    "motivation_letter",
    "recommendation",
    "research_proposal",
    "transcript",
    "other",
]


@pytest.mark.parametrize("track", Track.ALL)
@pytest.mark.parametrize("kind", KINDS)
def test_every_rubric_weights_to_one(kind: str, track: str):
    assert get_rubric(kind, track).total_weight == pytest.approx(1.0)


@pytest.mark.parametrize("track", Track.ALL)
@pytest.mark.parametrize("kind", KINDS)
def test_criterion_keys_are_unique_within_a_rubric(kind: str, track: str):
    keys = [c.key for c in get_rubric(kind, track).criteria]
    assert len(keys) == len(set(keys))


def test_unknown_kind_falls_back_rather_than_raising():
    rubric = get_rubric("passport_scan", Track.PHD)
    assert rubric.document_kind == "other"
    assert rubric.total_weight == pytest.approx(1.0)


def test_phd_weights_research_above_masters():
    phd = {c.key: c.weight for c in get_rubric("cv", Track.PHD).criteria}
    masters = {c.key: c.weight for c in get_rubric("cv", Track.MASTERS).criteria}
    # The whole point of the two tracks: a PhD committee reads for output.
    assert phd["research_output"] > masters["research_exposure"]


def test_phd_sop_demands_a_research_question():
    keys = {c.key for c in get_rubric("sop", Track.PHD).criteria}
    assert "research_question" in keys
    assert "supervisor_fit" in keys
    # A master's SOP is not judged on either.
    masters_keys = {c.key for c in get_rubric("sop", Track.MASTERS).criteria}
    assert "research_question" not in masters_keys


def test_review_prompt_carries_track_context_and_all_criteria():
    rubric = get_rubric("sop", Track.PHD)
    messages = document_review_prompt(
        rubric, Track.PHD, "sop", "My SOP", "Body text.", "artificial_intelligence", "ETH Zurich"
    )
    system, user = messages[0]["content"], messages[1]["content"]
    assert "DOCTORAL application" in system
    assert "fifteen years" in system
    assert "ETH Zurich" in system
    for criterion in rubric.criteria:
        assert criterion.key in user


def test_masters_and_phd_prompts_actually_differ():
    rubric_m = get_rubric("sop", Track.MASTERS)
    rubric_p = get_rubric("sop", Track.PHD)
    m = document_review_prompt(rubric_m, Track.MASTERS, "sop", "t", "b", None, None)[0]["content"]
    p = document_review_prompt(rubric_p, Track.PHD, "sop", "t", "b", None, None)[0]["content"]
    assert m != p
    assert "MASTER'S application" in m
    assert "five years of supervision" in p


def test_synthesis_prompt_lists_documents_and_gaps():
    messages = committee_synthesis_prompt(
        Track.PHD,
        "data_science",
        "MIT",
        [{"title": "CV", "kind": "cv", "score": 72.0, "summary": "Solid.", "findings": []}],
        ["cv"],
        ["sop", "recommendation"],
    )
    user = messages[1]["content"]
    assert "CV" in user
    assert "sop" in user or "recommendation" in user
