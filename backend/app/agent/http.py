"""Polite HTTP client for the crawler: shared UA, timeouts, and robots.txt checks."""

import asyncio
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

_robots_cache: dict[str, RobotFileParser | None] = {}
_robots_lock = asyncio.Lock()


def build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.agent_request_timeout,
        follow_redirects=True,
        headers={
            "User-Agent": settings.agent_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )


async def _load_robots(client: httpx.AsyncClient, origin: str) -> RobotFileParser | None:
    parser = RobotFileParser()
    try:
        response = await client.get(urljoin(origin, "/robots.txt"))
        if response.status_code >= 400:
            return None
        parser.parse(response.text.splitlines())
        return parser
    except httpx.HTTPError:
        return None


async def allowed_by_robots(client: httpx.AsyncClient, url: str) -> bool:
    """A missing or unreachable robots.txt is treated as allow, which is the
    convention; an explicit Disallow is always honoured."""
    if not settings.agent_respect_robots:
        return True

    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    async with _robots_lock:
        if origin not in _robots_cache:
            _robots_cache[origin] = await _load_robots(client, origin)
        parser = _robots_cache[origin]

    if parser is None:
        return True
    return parser.can_fetch(settings.agent_user_agent, url)


async def fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    if not await allowed_by_robots(client, url):
        log.info("robots_disallowed", url=url)
        return None
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        log.warning("fetch_failed", url=url, error=str(exc))
        return None
    if response.status_code >= 400:
        log.warning("fetch_status", url=url, status=response.status_code)
        return None
    return response.text
