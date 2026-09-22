"""Title-based filtering of listing pages, before any detail fetch."""

from types import SimpleNamespace

from app.agent.adapters.html_listing import HTMLListingAdapter


def _result(*titles: str):
    return SimpleNamespace(
        opportunities=[SimpleNamespace(title=title) for title in titles]
    )


SOURCE = SimpleNamespace(slug="georgia-tech-computing")


def _titles(result):
    return [item.title for item in result.opportunities]


def test_require_keeps_only_degree_headings():
    """Georgia Tech reuses the programme card class for a news rail."""
    result = _result(
        "Master of Science in Computer Science",
        "Ph.D. in Machine Learning",
        "Computing Grad Pursues Parallel Paths in Computer Science and Film",
    )
    HTMLListingAdapter._filter_titles(
        result, SOURCE, [r"\bmaster\b", r"\bPh\.?D\b"], keep_matches=True
    )
    assert _titles(result) == [
        "Master of Science in Computer Science",
        "Ph.D. in Machine Learning",
    ]


def test_exclude_drops_undergraduate_study():
    result = _result(
        "Bachelor of Science in Computer Science",
        "Master of Science in Robotics",
    )
    HTMLListingAdapter._filter_titles(
        result, SOURCE, [r"\bbachelor\b"], keep_matches=False
    )
    assert _titles(result) == ["Master of Science in Robotics"]


def test_no_patterns_leaves_the_listing_untouched():
    result = _result("MS in Data Science", "Anything at all")
    for patterns in (None, []):
        HTMLListingAdapter._filter_titles(result, SOURCE, patterns, keep_matches=True)
    assert len(result.opportunities) == 2


def test_matching_is_case_insensitive():
    result = _result("BACHELOR OF SCIENCE IN CS")
    HTMLListingAdapter._filter_titles(
        result, SOURCE, [r"\bbachelor\b"], keep_matches=False
    )
    assert result.opportunities == []
