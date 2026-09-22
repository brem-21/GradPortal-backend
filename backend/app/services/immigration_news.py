"""Live immigration and student-mobility news for the Counsel rail.

The rail sits behind the advisor pane and would otherwise be empty until the
user asks something, so it opens on worldwide immigration headlines. Feeds are
fetched in parallel and cached in-process: the rail is read-only, every user
sees the same headlines, and a shared cache keeps us from hitting five
government endpoints on every page load.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
import httpx
import structlog

log = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 30 * 60
FETCH_TIMEOUT_SECONDS = 8.0
MAX_ITEMS = 24


@dataclass(frozen=True)
class Feed:
    source: str
    url: str
    region: str
    # Departmental feeds carry every announcement the department makes, not
    # just immigration ones, so those are narrowed by keyword.
    topical: bool = True


# Verified reachable and parsing on 2026-09-22. USCIS, Times Higher Education
# and Erudera were tried and dropped: empty feed and two 404s respectively.
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
        topical=False,
    ),
    Feed(source="ICEF Monitor", url="https://monitor.icef.com/feed/", region="Worldwide"),
    Feed(source="The PIE News", url="https://thepienews.com/feed/", region="Worldwide"),
    Feed(
        source="Study International",
        url="https://www.studyinternational.com/feed/",
        region="Worldwide",
    ),
)

KEYWORDS = (
    "immigration",
    "immigrant",
    "visa",
    "permit",
    "permanent residence",
    "express entry",
    "citizenship",
    "asylum",
    "refugee",
    "border",
    "international student",
    "study permit",
    "work permit",
    "migration",
    "migrant",
    "newcomer",
)

_cache: tuple[float, list[dict]] | None = None
_lock = asyncio.Lock()


def _is_relevant(title: str, summary: str) -> bool:
    haystack = f"{title} {summary}".lower()
    return any(word in haystack for word in KEYWORDS)


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
        summary = (entry.get("summary") or "").strip()
        if not feed.topical and not _is_relevant(title, summary):
            continue
        published = _published_at(entry)
        items.append(
            {
                "title": title,
                "url": link,
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

    seen: set[str] = set()
    items: list[dict] = []
    for batch in batches:
        for item in batch:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            items.append(item)

    items.sort(key=lambda item: item["_sort"], reverse=True)
    for item in items:
        item.pop("_sort", None)
    return items[:MAX_ITEMS]


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
