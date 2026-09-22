from functools import lru_cache

from shared.config import EmbeddingSettings

SCHEMA = "docs"


class DocSettings(EmbeddingSettings):
    service_name: str = "doc-service"
    port: int = 8001

    max_upload_bytes: int = 15 * 1024 * 1024
    document_storage_dir: str = "./.storage"

    # Chunking. 800 tokens keeps a CV bullet cluster or an SOP paragraph intact;
    # the overlap stops a sentence that straddles a boundary from being lost.
    chunk_tokens: int = 800
    chunk_overlap_tokens: int = 120
    max_chunks_per_document: int = 400


@lru_cache
def get_settings() -> DocSettings:
    return DocSettings()


settings = get_settings()
