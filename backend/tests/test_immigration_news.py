"""The filtering that keeps the Counsel newswire about immigration."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services import immigration_news as news


def _entry(title: str, *, link: str | None = None, days_old: int = 1, summary: str = ""):
    published = datetime.now(UTC) - timedelta(days=days_old)
    return {
        "title": title,
        "link": link or f"https://example.com/{abs(hash(title))}",
        "summary": summary,
        "published_parsed": published.timetuple()[:9],
    }


class _Parsed:
    def __init__(self, entries):
        self.entries = entries


@pytest.fixture
def parse_entries(monkeypatch):
    def _install(entries):
        monkeypatch.setattr(news.feedparser, "parse", lambda _body: _Parsed(entries))

    return _install


DEPARTMENTAL = news.Feed(source="IRCC", url="x", region="Canada")
TOPICAL = news.Feed(source="Home Office", url="x", region="UK")


def test_departmental_feed_keeps_only_student_immigration_headlines(parse_entries):
    parse_entries(
        [
            _entry("Canada caps study permits for a second year"),
            _entry("Canada proposes new regulations to modernize the asylum process"),
            _entry("Government announces changes to the fuel excise tax"),
        ]
    )
    titles = [item["title"] for item in news._parse(DEPARTMENTAL, b"")]
    assert titles == ["Canada caps study permits for a second year"]


def test_department_name_in_the_summary_does_not_qualify_an_item(parse_entries):
    """Every IRCC entry carries the department's name; only the headline counts."""
    parse_entries(
        [
            _entry(
                "Minister highlights launch of National Food Security Strategy",
                summary="Immigration, Refugees and Citizenship Canada today announced...",
            )
        ]
    )
    assert news._parse(DEPARTMENTAL, b"") == []


def test_press_advisories_are_dropped(parse_entries):
    parse_entries(
        [
            _entry("Minister Diab to participate in a citizenship ceremony in Ottawa"),
            _entry("Media advisory: student visa processing update"),
        ]
    )
    assert news._parse(DEPARTMENTAL, b"") == []


def test_a_dedicated_feed_is_narrowed_too(parse_entries):
    """Even the Home Office feed carries items a student has no use for."""
    parse_entries(
        [
            _entry("More children eligible for eGates this summer"),
            _entry("Student visa sponsor licence rules tightened"),
        ]
    )
    titles = [item["title"] for item in news._parse(TOPICAL, b"")]
    assert titles == ["Student visa sponsor licence rules tightened"]


def test_items_older_than_the_window_are_dropped(parse_entries):
    parse_entries(
        [
            _entry("Recent student visa rule change", days_old=3),
            _entry("Ancient student visa rule change", days_old=news.MAX_AGE_DAYS + 5),
        ]
    )
    titles = [item["title"] for item in news._parse(TOPICAL, b"")]
    assert titles == ["Recent student visa rule change"]


def test_entries_without_a_link_are_skipped(parse_entries):
    parse_entries([{"title": "Student visa news", "link": "", "summary": ""}])
    assert news._parse(TOPICAL, b"") == []


def test_interleave_stops_one_feed_filling_the_rail():
    items = [
        {"source": "PIE", "title": f"pie-{index}"} for index in range(5)
    ] + [{"source": "IRCC", "title": "ircc-0"}]
    ordered = [item["title"] for item in news._interleave(items)]
    assert ordered[:2] == ["pie-0", "ircc-0"]
    assert len(ordered) == 6


@pytest.mark.anyio
async def test_a_dead_feed_yields_no_items_rather_than_raising():
    class Dead:
        async def get(self, _url):
            raise RuntimeError("unreachable")

    assert await news._fetch(Dead(), TOPICAL) == []


@pytest.mark.anyio
async def test_stale_headlines_are_kept_when_every_feed_fails(monkeypatch):
    """An empty rail reads worse than yesterday's news."""
    cached = [{"title": "Visa rule change", "url": "https://example.com/1"}]
    monkeypatch.setattr(news, "_cache", (0.0, cached))
    monkeypatch.setattr(news, "_collect", lambda: _empty())

    assert await news.latest(limit=5, refresh=True) == cached


async def _empty() -> list[dict]:
    return []


class TestStudentFocus:
    """The rail is for people applying abroad, not general immigration."""

    @pytest.mark.parametrize(
        "title",
        [
            "Australia moves to reduce net migration with new restrictions on students",
            "August applications for UK study visas fall 16% in just a year",
            "Judge signals possible halt to US student visa duration rule",
            "Canada caps study permits for a second year",
            "New PGWP eligibility rules take effect",
        ],
    )
    def test_student_immigration_headlines_are_kept(self, title):
        assert news._is_relevant(title)

    @pytest.mark.parametrize(
        "title",
        [
            "Canada marks World Refugee Day and reflects on refugee protection",
            "Asylum appeals target launched for faster removals",
            "Government announces changes to the fuel excise tax",
            "Canada and Manitoba join forces on Francophone immigration",
            "Three new universities open in the north",
        ],
    )
    def test_general_news_is_dropped(self, title):
        assert not news._is_relevant(title)


class TestSummaries:
    def test_html_is_stripped_and_entities_decoded(self):
        assert news._summarise("<p>UK &amp; Canada  <b>tighten</b> rules</p>") == (
            "UK & Canada tighten rules"
        )

    def test_empty_summary_becomes_none(self):
        assert news._summarise("<p> </p>") is None

    def test_long_summaries_are_cut_on_a_word_boundary(self):
        summary = news._summarise("word " * 200)
        assert summary is not None
        assert len(summary) <= news.SUMMARY_LIMIT + 1
        assert summary.endswith("…")
        assert "wor…" not in summary
