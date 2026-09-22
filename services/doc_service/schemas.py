import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str | None
    filename: str
    content_type: str
    size_bytes: int
    page_count: int | None
    word_count: int
    chunk_count: int
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentRead):
    extracted_text: str


class DocumentList(BaseModel):
    items: list[DocumentRead]
    total: int


class UploadResult(BaseModel):
    document: DocumentRead
    warnings: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """Internal. rag-service and eval-service never embed anything themselves —
    doc-service owns the embedding provider so there is one place to swap it."""

    user_key: str
    query: str
    top_k: int = Field(8, ge=1, le=50)
    document_ids: list[uuid.UUID] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)
    # Cosine distance cutoff. Above this the chunk is noise, and feeding noise
    # to a grounded assistant is how it starts inventing.
    max_distance: float = 0.75


class ChunkHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    document_kind: str
    chunk_index: int
    content: str
    page_number: int | None
    section: str | None
    distance: float

    @property
    def score(self) -> float:
        return round(1.0 - self.distance, 4)


class SearchResponse(BaseModel):
    hits: list[ChunkHit]
    query: str
    embedding_model: str


class InternalDocumentText(BaseModel):
    id: uuid.UUID
    kind: str
    title: str | None
    filename: str
    word_count: int
    page_count: int | None
    extracted_text: str


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=96)


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    model: str
    dimensions: int


class UpdateDocument(BaseModel):
    kind: str | None = None
    title: str | None = None
