from functools import lru_cache

from shared.config import OpenRouterSettings

SCHEMA = "rag"


class RagSettings(OpenRouterSettings):
    service_name: str = "rag-service"
    port: int = 8002

    # Retrieval
    top_k: int = 8
    max_distance: float = 0.72
    # A second retrieval round only fires when the first is thin, so the common
    # case stays one round-trip.
    weak_retrieval_distance: float = 0.45
    min_strong_hits: int = 2
    max_search_rounds: int = 2
    max_queries_per_round: int = 3

    # Conversation
    history_turns: int = 8
    max_context_chars: int = 18000


@lru_cache
def get_settings() -> RagSettings:
    return RagSettings()


settings = get_settings()
