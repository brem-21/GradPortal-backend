from functools import lru_cache

from shared.config import OpenRouterSettings

SCHEMA = "evaluation"


class EvalSettings(OpenRouterSettings):
    service_name: str = "eval-service"
    port: int = 8003

    # Evaluation always uses the reasoning model. Judging an SOP against a rubric
    # is exactly the multi-criterion weighing that reasoning models are for, and
    # the cost per evaluation is small next to what an application costs a person.
    force_reasoning: bool = True
    max_documents_per_run: int = 8
    # A long SOP plus a CV can exceed a comfortable context; truncate per document.
    max_chars_per_document: int = 24000


@lru_cache
def get_settings() -> EvalSettings:
    return EvalSettings()


settings = get_settings()
