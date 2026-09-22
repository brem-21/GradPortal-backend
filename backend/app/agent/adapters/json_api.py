"""Adapter for sources that expose a JSON endpoint.

Covers official university APIs, Greenhouse/Lever boards used by research labs,
and any partner feed. Field mapping is declarative so a new endpoint is config.

Source.config:
  api_url        (required)
  items_path     dot-path to the array, e.g. "data.jobs" (default: root array)
  headers        dict of extra request headers
  mapping        {"title": "name", "url": "absolute_url", "description": "content", ...}
  organization / country / type_hint defaults
"""

from typing import Any

import httpx

from app.agent.base import AdapterResult, RawOpportunity, SourceAdapter
from app.agent.http import build_client
from app.agent.normalize import clean_text
from app.models import Source

DEFAULT_MAPPING = {
    "title": "title",
    "url": "url",
    "description": "description",
    "organization": "organization",
    "location": "location",
    "external_id": "id",
}


def _dig(payload: Any, path: str | None) -> Any:
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class JSONAPIAdapter(SourceAdapter):
    key = "json_api"
    label = "JSON API endpoint"

    async def fetch(self, source: Source) -> AdapterResult:
        config = source.config or {}
        api_url = config.get("api_url") or source.base_url
        if not api_url:
            return AdapterResult(skipped=True, skip_reason="No api_url configured")

        mapping = {**DEFAULT_MAPPING, **(config.get("mapping") or {})}
        result = AdapterResult()

        async with build_client() as client:
            try:
                response = await client.get(api_url, headers=config.get("headers") or {})
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                result.warnings.append(f"Request to {api_url} failed: {exc}")
                return result

        items = _dig(payload, config.get("items_path"))
        if not isinstance(items, list):
            result.warnings.append(
                f"items_path '{config.get('items_path')}' did not resolve to a list"
            )
            return result

        for item in items:
            if not isinstance(item, dict):
                continue
            title = clean_text(str(_dig(item, mapping["title"]) or ""))
            url = _dig(item, mapping["url"])
            if not title or not url:
                continue

            result.opportunities.append(
                RawOpportunity(
                    title=title,
                    url=str(url),
                    description=clean_text(str(_dig(item, mapping["description"]) or ""), 8000),
                    organization=str(
                        _dig(item, mapping.get("organization"))
                        or config.get("organization")
                        or source.name
                    ),
                    location=(lambda v: clean_text(str(v)) if v else None)(
                        _dig(item, mapping.get("location"))
                    ),
                    country=config.get("country"),
                    opportunity_type=config.get("type_hint"),
                    external_id=str(_dig(item, mapping.get("external_id")) or url),
                    raw={"api_url": api_url},
                )
            )

        return result
