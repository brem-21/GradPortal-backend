"""RSS/Atom adapter.

Many university graduate schools, research institutes and scholarship boards
publish an announcements feed. Feeds are the friendliest source available: they
are meant for machines, so there is no scraping question at all.

Source.config:
  feed_url        (required) the RSS/Atom URL
  organization    optional default organization name
  country         optional default country
  type_hint       optional default opportunity_type
  fetch_detail    bool, default true — pull the linked page for contacts
  max_items       int, default 40
"""

import asyncio
from datetime import UTC, datetime

import feedparser

from app.agent.base import AdapterResult, RawOpportunity, SourceAdapter
from app.agent.contacts import extract_contacts_from_html
from app.agent.http import build_client, fetch_text
from app.agent.normalize import clean_text
from app.core.config import settings
from app.models import Source


class RSSFeedAdapter(SourceAdapter):
    key = "rss_feed"
    label = "RSS / Atom feed"

    async def fetch(self, source: Source) -> AdapterResult:
        config = source.config or {}
        feed_url = config.get("feed_url") or source.base_url
        if not feed_url:
            return AdapterResult(skipped=True, skip_reason="No feed_url configured")

        result = AdapterResult()
        max_items = int(config.get("max_items", 40))
        fetch_detail = bool(config.get("fetch_detail", True))

        async with build_client() as client:
            body = await fetch_text(client, feed_url)
            if body is None:
                result.warnings.append(f"Could not fetch feed {feed_url}")
                return result

            parsed = feedparser.parse(body)
            if parsed.bozo and not parsed.entries:
                result.warnings.append(f"Malformed feed: {parsed.bozo_exception}")
                return result

            entries = parsed.entries[:max_items]
            for entry in entries:
                link = entry.get("link")
                title = clean_text(entry.get("title"))
                if not link or not title:
                    continue

                description = clean_text(entry.get("summary") or entry.get("description") or "")
                posted_at = None
                if entry.get("published_parsed"):
                    posted_at = datetime(*entry.published_parsed[:6], tzinfo=UTC)
                elif entry.get("updated_parsed"):
                    posted_at = datetime(*entry.updated_parsed[:6], tzinfo=UTC)

                result.opportunities.append(
                    RawOpportunity(
                        title=title,
                        url=link,
                        description=description,
                        organization=config.get("organization") or source.name,
                        country=config.get("country"),
                        opportunity_type=config.get("type_hint"),
                        posted_at=posted_at,
                        external_id=entry.get("id") or link,
                        raw={"feed_url": feed_url},
                    )
                )

            if fetch_detail:
                await self._enrich(client, result.opportunities)

        return result

    async def _enrich(self, client, opportunities: list[RawOpportunity]) -> None:
        """Pull each detail page once, for the fuller description and its contacts."""
        semaphore = asyncio.Semaphore(settings.agent_max_concurrency)

        async def load(opportunity: RawOpportunity) -> None:
            async with semaphore:
                html = await fetch_text(client, opportunity.url)
            if not html:
                return
            opportunity.detail_html = html
            opportunity.contacts = extract_contacts_from_html(html, opportunity.url)

        await asyncio.gather(*(load(o) for o in opportunities))
