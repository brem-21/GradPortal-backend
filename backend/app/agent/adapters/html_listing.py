"""Generic CSS-selector adapter for admissions, scholarship and vacancy listing pages.

This is the workhorse: point it at a listing URL, give it selectors, and it yields
opportunities. Adding a new university is a database row, not a code change.

Source.config:
  list_url          (required) page holding the listing
  item_selector     (required) CSS selector for one row/card
  title_selector    CSS within item; defaults to the item's first heading or link
  link_selector     CSS within item; defaults to the first <a>
  summary_selector  CSS within item for the blurb
  deadline_selector CSS within item for an explicit deadline cell
  location_selector CSS within item
  pagination        {"param": "page", "start": 1, "pages": 3} — optional
  organization / country / type_hint / degree_hint  defaults applied to every item
  fetch_detail      bool, default true
  detail_selector   CSS on the detail page holding the main body
  max_items         int, default 60
"""

import asyncio
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.agent.base import AdapterResult, RawOpportunity, SourceAdapter
from app.agent.contacts import extract_contacts_from_html
from app.agent.http import build_client, fetch_text
from app.agent.normalize import clean_text
from app.core.config import settings
from app.models import Source


def _text_of(node, selector: str | None) -> str:
    if node is None:
        return ""
    target = node.css_first(selector) if selector else node
    return clean_text(target.text(separator=" ", strip=True)) if target else ""


class HTMLListingAdapter(SourceAdapter):
    key = "html_listing"
    label = "HTML listing page (CSS selectors)"

    async def fetch(self, source: Source) -> AdapterResult:
        config = source.config or {}
        list_url = config.get("list_url") or source.base_url
        item_selector = config.get("item_selector")

        if not list_url:
            return AdapterResult(skipped=True, skip_reason="No list_url configured")
        if not item_selector:
            return AdapterResult(skipped=True, skip_reason="No item_selector configured")

        result = AdapterResult()
        max_items = int(config.get("max_items", 60))

        async with build_client() as client:
            for page_url in self._page_urls(list_url, config):
                if len(result.opportunities) >= max_items:
                    break
                html = await fetch_text(client, page_url)
                if html is None:
                    result.warnings.append(f"Could not fetch {page_url}")
                    continue
                self._parse_listing(html, page_url, config, source, result, max_items)

            if config.get("fetch_detail", True):
                await self._enrich(client, result.opportunities, config)

        if not result.opportunities:
            result.warnings.append(
                f"Selector '{item_selector}' matched nothing — the page layout may have changed."
            )
        return result

    def _page_urls(self, list_url: str, config: dict) -> list[str]:
        pagination = config.get("pagination")
        if not pagination:
            return [list_url]
        param = pagination.get("param", "page")
        start = int(pagination.get("start", 1))
        pages = int(pagination.get("pages", 1))
        separator = "&" if "?" in list_url else "?"
        return [f"{list_url}{separator}{param}={start + i}" for i in range(pages)]

    def _parse_listing(
        self,
        html: str,
        page_url: str,
        config: dict,
        source: Source,
        result: AdapterResult,
        max_items: int,
    ) -> None:
        tree = HTMLParser(html)
        for item in tree.css(config["item_selector"]):
            if len(result.opportunities) >= max_items:
                return

            title = _text_of(item, config.get("title_selector"))
            if not title:
                heading = item.css_first("h1, h2, h3, h4") or item.css_first("a")
                title = clean_text(heading.text(strip=True)) if heading else ""
            if not title:
                continue

            link_node = (
                item.css_first(config["link_selector"])
                if config.get("link_selector")
                else item.css_first("a[href]")
            )
            href = link_node.attributes.get("href") if link_node else None
            if not href:
                continue
            url = urljoin(page_url, href)

            summary = _text_of(item, config.get("summary_selector"))
            if not summary:
                summary = clean_text(item.text(separator=" ", strip=True), limit=400)

            result.opportunities.append(
                RawOpportunity(
                    title=title,
                    url=url,
                    description=summary,
                    summary=clean_text(summary, limit=280),
                    organization=config.get("organization") or source.name,
                    department=config.get("department"),
                    country=config.get("country"),
                    location=_text_of(item, config.get("location_selector")) or None,
                    opportunity_type=config.get("type_hint"),
                    degree_levels=list(config.get("degree_hint", [])),
                    deadline_text=_text_of(item, config.get("deadline_selector")) or None,
                    external_id=url,
                    raw={"list_url": page_url},
                )
            )

    async def _enrich(self, client, opportunities: list[RawOpportunity], config: dict) -> None:
        semaphore = asyncio.Semaphore(settings.agent_max_concurrency)
        detail_selector = config.get("detail_selector")

        async def load(opportunity: RawOpportunity) -> None:
            async with semaphore:
                html = await fetch_text(client, opportunity.url)
            if not html:
                return
            opportunity.detail_html = html
            tree = HTMLParser(html)
            body_node = tree.css_first(detail_selector) if detail_selector else (tree.body or tree)
            if body_node:
                body = clean_text(body_node.text(separator=" ", strip=True), limit=8000)
                if len(body) > len(opportunity.description):
                    opportunity.description = body
            opportunity.contacts = extract_contacts_from_html(html, opportunity.url)

        await asyncio.gather(*(load(o) for o in opportunities))
