"""Live immigration and student-mobility news for the Counsel rail.

The rail sits behind the advisor pane and would otherwise be empty until the
user asks something, so it opens on worldwide immigration headlines. Feeds are
fetched in parallel and cached in-process: the rail is read-only, every user
sees the same headlines, and a shared cache keeps us from hitting five
government endpoints on every page load.
"""

from __future__ import annotations

import asyncio
import html
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import feedparser
import httpx
import structlog

log = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 30 * 60
FETCH_TIMEOUT_SECONDS = 8.0
MAX_ITEMS = 24
# The rail is billed as live news, so anything older than a term is dropped
# rather than allowed to outrank this week's headlines in the round-robin.
MAX_AGE_DAYS = 120


@dataclass(frozen=True)
class Feed:
    source: str
    url: str
    region: str


# Verified reachable and parsing on 2026-09-22. Every feed is narrowed by
# headline — even the dedicated immigration ones carry general asylum and
# border reporting that is not a prospective student's news.
# Tried and dropped: USCIS, StudyTravel, EducationUSA and Studyportals (empty
# feeds); Times Higher Education, UKCISA, Erudera and AU Home Affairs (404).
FEEDS: tuple[Feed, ...] = (
    Feed(
        source="UK Visas and Immigration",
        url=(
            "https://www.gov.uk/search/news-and-communications.atom"
            "?organisations%5B%5D=uk-visas-and-immigration"
        ),
        region="United Kingdom",
    ),
    Feed(
        source="Immigration, Refugees and Citizenship Canada",
        url=(
            "https://api.io.canada.ca/io-server/gc/news/en/v2"
            "?dept=departmentofcitizenshipandimmigration&sort=publishedDate"
            "&orderBy=desc&publishedDate%3E=2021-07-23&pick=100&format=atom"
        ),
        region="Canada",
    ),
    Feed(source="ICEF Monitor", url="https://monitor.icef.com/feed/", region="Worldwide"),
    Feed(
        source="The PIE News — Immigration",
        url="https://thepienews.com/category/news/immigration/feed/",
        region="Worldwide",
    ),
    Feed(source="Schengen News", url="https://schengen.news/feed/", region="Europe"),
    Feed(source="The PIE News", url="https://thepienews.com/feed/", region="Worldwide"),
    Feed(
        source="Study International",
        url="https://www.studyinternational.com/feed/",
        region="Worldwide",
    ),
)

# What the rail is for: immigration as it lands on someone applying abroad to
# study. Generic asylum, refugee and border reporting is immigration news but
# not this reader's news, so it is not enough on its own.
STUDENT_PHRASES = (
    "international student",
    "international education",
    "international recruitment",
    "student visa",
    "student route",
    "study permit",
    "study visa",
    "studying abroad",
    "study abroad",
    "post-study work",
    "post study work",
    "graduate route",
    "post-graduation work permit",
    "pgwp",
    "optional practical training",
    "f-1",
    "f1 visa",
    "j-1",
    "sevis",
    "i-20",
    "confirmation of acceptance",
    "sponsor licence",
    "sponsor license",
    "student mobility",
    "student dependant",
    "student dependent",
    "study abroad visa",
    "graduate visa",
    "scholarship visa",
)

# Anything that moves a person between countries.
MOVEMENT_TERMS = (
    "visa",
    "permit",
    "immigration",
    "immigrant",
    "migration",
    "migrant",
    "residency",
    "permanent residence",
    "express entry",
    "citizenship",
    "deportation",
    "sponsorship",
    "work rights",
    "newcomer",
    "border",
)

# Anything that places it in education.
STUDY_TERMS = (
    "student",
    "study",
    "studies",
    "graduate",
    "postgraduate",
    "undergraduate",
    "universit",
    "college",
    "campus",
    "tuition",
    "enrol",
    "enroll",
    "academic",
    "scholarship",
    "phd",
    "master",
)

# Government feeds announce upcoming press events. They match the keywords
# but carry no news, so they are dropped by phrase.
NOISE = (
    "to make an announcement",
    "media advisory",
    "will hold a media",
    "notice to media",
    "to hold media availability",
    "to participate in",
    "to attend",
    "to deliver remarks",
)

_cache: tuple[float, list[dict]] | None = None
_lock = asyncio.Lock()


def _is_relevant(title: str) -> bool:
    """Match on the headline alone.

    Summaries are not usable here: every IRCC entry carries the department's
    own name, "Immigration, Refugees and Citizenship Canada", in its boilerplate,
    so matching the body would pass the department's every announcement through.
    """
    haystack = title.lower()
    if any(phrase in haystack for phrase in NOISE):
        return False
    if any(phrase in haystack for phrase in STUDENT_PHRASES):
        return True
    # No named student route in the headline, so it only counts if it is about
    # both crossing a border and studying — "Canada caps study permits" passes,
    # "Canada marks World Refugee Day" does not.
    return any(word in haystack for word in MOVEMENT_TERMS) and any(
        word in haystack for word in STUDY_TERMS
    )


_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
SUMMARY_LIMIT = 220


def _summarise(raw: str) -> str | None:
    """Feed summaries arrive as HTML; the rail shows a short plain-text preview."""
    text = _WHITESPACE.sub(" ", html.unescape(_TAG.sub(" ", raw))).strip()
    if not text:
        return None
    if len(text) <= SUMMARY_LIMIT:
        return text
    # Cut on a word boundary so the preview does not end mid-word.
    return text[:SUMMARY_LIMIT].rsplit(" ", 1)[0] + "…"


def _published_at(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=UTC)


def _parse(feed: Feed, body: bytes) -> list[dict]:
    parsed = feedparser.parse(body)
    items: list[dict] = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        if not _is_relevant(title):
            continue
        summary = _summarise(entry.get("summary") or "")
        published = _published_at(entry)
        if published and published < datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS):
            continue
        items.append(
            {
                "title": title,
                "url": link,
                "summary": summary,
                "source": feed.source,
                "region": feed.region,
                "published_at": published.isoformat() if published else None,
                "_sort": published or datetime.min.replace(tzinfo=UTC),
            }
        )
    return items


async def _fetch(client: httpx.AsyncClient, feed: Feed) -> list[dict]:
    try:
        response = await client.get(feed.url)
        response.raise_for_status()
        # feedparser is synchronous and does real XML work, so keep it off the
        # event loop while the other feeds are still in flight.
        return await asyncio.to_thread(_parse, feed, response.content)
    except Exception as exc:  # one dead feed must not empty the whole rail
        log.warning("news_feed_failed", source=feed.source, error=str(exc))
        return []


async def _collect() -> list[dict]:
    headers = {"User-Agent": "GradPortal/1.0 (+https://gradportal.example.com)"}
    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True, headers=headers
    ) as client:
        batches = await asyncio.gather(*(_fetch(client, feed) for feed in FEEDS))

    # The same story reaches us twice when a feed republishes it under a new
    # URL, so headlines are deduplicated as well as links.
    seen: set[str] = set()
    items: list[dict] = []
    for batch in batches:
        for item in batch:
            keys = (item["url"], item["title"].casefold())
            if any(key in seen for key in keys):
                continue
            seen.update(keys)
            items.append(item)

    items.sort(key=lambda item: item["_sort"], reverse=True)
    return _interleave(items)[:MAX_ITEMS]


def _interleave(items: list[dict]) -> list[dict]:
    """Round-robin across sources so one prolific feed cannot fill the rail.

    Sources are visited newest-first and each contributes its next headline in
    turn, so the rail stays broadly recent while showing a spread of origins.
    """
    by_source: dict[str, list[dict]] = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)

    ordered: list[dict] = []
    queues = list(by_source.values())
    while queues:
        for queue in list(queues):
            ordered.append(queue.pop(0))
            if not queue:
                queues.remove(queue)
    for item in ordered:
        item.pop("_sort", None)
    return ordered


async def latest(limit: int = 12, *, refresh: bool = False) -> list[dict]:
    """Newest immigration headlines, newest first, served from a shared cache."""
    global _cache

    async with _lock:
        fresh = _cache is not None and time.monotonic() - _cache[0] < CACHE_TTL_SECONDS
        if refresh or not fresh:
            items = await _collect()
            # Keep the previous headlines if every feed failed — a stale rail
            # reads better than an empty one.
            if items or _cache is None:
                _cache = (time.monotonic(), items)
        return list(_cache[1][:limit])
