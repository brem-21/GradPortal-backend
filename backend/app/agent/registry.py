from app.agent.adapters.handshake import HandshakeAdapter
from app.agent.adapters.html_listing import HTMLListingAdapter
from app.agent.adapters.json_api import JSONAPIAdapter
from app.agent.adapters.linkedin import LinkedInAdapter
from app.agent.adapters.rss_feed import RSSFeedAdapter
from app.agent.base import SourceAdapter

_ADAPTERS: dict[str, SourceAdapter] = {
    adapter.key: adapter
    for adapter in (
        HTMLListingAdapter(),
        RSSFeedAdapter(),
        JSONAPIAdapter(),
        LinkedInAdapter(),
        HandshakeAdapter(),
    )
}


def get_adapter(key: str) -> SourceAdapter | None:
    return _ADAPTERS.get(key)


def list_adapters() -> list[dict]:
    return [
        {
            "key": adapter.key,
            "label": adapter.label,
            "requires_credentials": adapter.requires_credentials,
            "configured": adapter.is_configured(),
        }
        for adapter in _ADAPTERS.values()
    ]
