from functools import lru_cache

from shared.config import OpenRouterSettings

SCHEMA = "rag"


class RagSettings(OpenRouterSettings):
    service_name: str = "rag-service"
    port: int = 8002

    # Retrieval.
    #
    # Thresholds measured against text-embedding-3-small on real application
    # documents, not guessed. Cosine distances observed for a one-page CV:
    #
    #   0.56  "data engineering internship Airflow"  (specific, present)
    #   0.70  "research experience"                  (present)
    #   0.72  "teaching experience"                  (absent)
    #   0.81  "machine learning segmentation model"  (present)
    #   0.86  "what is my GPA"                       (present)
    #   0.90  "favourite pizza topping"              (absurd)
    #
    # Relevant and irrelevant overlap heavily, because a short document is one
    # chunk and its vector averages everything in it. Distance therefore cannot
    # decide whether an answer is possible — only the model, reading the actual
    # text, can. So max_distance is set to exclude the plainly absurd and
    # nothing else, and sufficiency no longer depends on a distance floor.
    top_k: int = 8
    max_distance: float = 0.88
    # Used only to decide whether a second, reworded search is worth running.
    # One strong hit is enough: requiring two meant the second round fired on
    # almost every question (relevant matches sit at 0.56-0.86, so rarely do
    # two land under 0.62), adding a planning call plus three more searches —
    # several seconds — to answers the first round had already covered.
    strong_hit_distance: float = 0.62
    min_strong_hits: int = 1
    max_search_rounds: int = 2
    max_queries_per_round: int = 3

    # Conversation
    history_turns: int = 8
    max_context_chars: int = 18000


@lru_cache
def get_settings() -> RagSettings:
    return RagSettings()


settings = get_settings()
