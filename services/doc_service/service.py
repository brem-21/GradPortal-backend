"""Ingest pipeline: bytes in, indexed chunks out."""

import uuid

import structlog
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from doc_service import storage
from doc_service.chunking import chunk_document
from doc_service.config import settings
from doc_service.models import Document, DocumentChunk, DocumentStatus
from doc_service.parsing import parse
from doc_service.schemas import ChunkHit
from shared.embeddings import EmbeddingClient
from shared.errors import NotFoundError, ProviderNotConfigured, ValidationError

log = structlog.get_logger(__name__)

embeddings = EmbeddingClient(settings)


def get_owned(db: Session, document_id: uuid.UUID, user_key: str) -> Document:
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.user_key == user_key)
    )
    if document is None:
        # Same response whether it is missing or someone else's — never confirm
        # that another user's document exists.
        raise NotFoundError("Document not found")
    return document


async def index_document(db: Session, document: Document) -> None:
    """Chunk and embed a parsed document. Replaces any existing chunks."""
    document.status = DocumentStatus.PROCESSING
    document.error = None
    db.flush()

    db.execute(sql_delete(DocumentChunk).where(DocumentChunk.document_id == document.id))

    chunks = chunk_document(
        document.extracted_text,
        max_tokens=settings.chunk_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
        page_offsets=(document.meta or {}).get("page_offsets") or [],
        max_chunks=settings.max_chunks_per_document,
    )
    if not chunks:
        document.status = DocumentStatus.FAILED
        document.error = "Nothing could be chunked from this document."
        document.chunk_count = 0
        db.flush()
        return

    try:
        vectors = await embeddings.embed([chunk.content for chunk in chunks])
    except ProviderNotConfigured:
        # A missing key is a deployment problem, not a document problem. Let it
        # surface as a 503 so the caller is told what to fix; the transaction
        # rolls back and `ingest` removes the stored file.
        raise
    except Exception as exc:
        # Anything else (rate limit, timeout, a single bad chunk) is worth
        # keeping the row for, so the user can retry without re-uploading.
        document.status = DocumentStatus.FAILED
        document.error = str(exc)[:1000]
        db.flush()
        log.warning("embedding_failed", document_id=str(document.id), error=str(exc))
        return

    for chunk, vector in zip(chunks, vectors, strict=True):
        db.add(
            DocumentChunk(
                document_id=document.id,
                user_key=document.user_key,
                chunk_index=chunk.index,
                content=chunk.content,
                token_count=chunk.token_count,
                page_number=chunk.page_number,
                section=chunk.section,
                embedding=vector,
            )
        )

    document.chunk_count = len(chunks)
    document.status = DocumentStatus.INDEXED
    db.flush()
    log.info(
        "document_indexed",
        document_id=str(document.id),
        kind=document.kind,
        chunks=len(chunks),
        words=document.word_count,
    )


async def ingest(
    db: Session,
    *,
    user_key: str,
    data: bytes,
    filename: str,
    content_type: str,
    kind: str,
    title: str | None,
) -> tuple[Document, list[str]]:
    if not data:
        raise ValidationError("The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise ValidationError(f"That file is larger than the {limit_mb}MB limit.")

    digest = storage.content_hash(data)
    existing = db.scalar(
        select(Document).where(Document.user_key == user_key, Document.sha256 == digest)
    )
    if existing is not None:
        # Re-uploading the same bytes is almost always a mistake or a retry;
        # refresh the classification instead of creating a duplicate.
        existing.kind = kind or existing.kind
        if title:
            existing.title = title
        db.flush()
        if existing.status != DocumentStatus.INDEXED:
            await index_document(db, existing)
        return existing, ["You had already uploaded this file; the existing copy was reused."]

    parsed = parse(data, content_type, filename)
    storage_path = storage.save(user_key, digest, filename, data)

    document = Document(
        user_key=user_key,
        kind=kind,
        title=title or filename.rsplit(".", 1)[0][:500],
        filename=filename[:500],
        content_type=content_type or "application/octet-stream",
        size_bytes=len(data),
        sha256=digest,
        storage_path=storage_path,
        extracted_text=parsed.text,
        page_count=parsed.page_count,
        word_count=len(parsed.text.split()),
        status=DocumentStatus.PENDING,
        meta={"page_offsets": parsed.page_offsets, "warnings": parsed.warnings},
    )
    db.add(document)
    db.flush()

    try:
        await index_document(db, document)
    except Exception:
        # The DB row will roll back, so the file on disk would be orphaned.
        storage.delete(storage_path)
        raise

    return document, parsed.warnings


async def search(
    db: Session,
    *,
    user_key: str,
    query: str,
    top_k: int,
    document_ids: list[uuid.UUID] | None = None,
    kinds: list[str] | None = None,
    max_distance: float = 0.75,
) -> list[ChunkHit]:
    """Nearest chunks for one user. The user filter is not optional."""
    if not query.strip():
        return []

    vector = await embeddings.embed_one(query)
    distance = DocumentChunk.embedding.cosine_distance(vector).label("distance")

    statement = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.content,
            DocumentChunk.page_number,
            DocumentChunk.section,
            Document.title,
            Document.filename,
            Document.kind,
            distance,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.user_key == user_key,
            Document.status == DocumentStatus.INDEXED,
        )
        .order_by(distance)
        .limit(top_k)
    )
    if document_ids:
        statement = statement.where(DocumentChunk.document_id.in_(document_ids))
    if kinds:
        statement = statement.where(Document.kind.in_(kinds))

    rows = db.execute(statement).all()
    return [
        ChunkHit(
            chunk_id=row.id,
            document_id=row.document_id,
            document_title=row.title or row.filename,
            document_kind=row.kind,
            chunk_index=row.chunk_index,
            content=row.content,
            page_number=row.page_number,
            section=row.section,
            distance=float(row.distance),
        )
        for row in rows
        if float(row.distance) <= max_distance
    ]


def delete_document(db: Session, document: Document) -> None:
    storage.delete(document.storage_path)
    db.delete(document)


def stats(db: Session, user_key: str) -> dict:
    rows = db.execute(
        select(Document.kind, func.count(), func.sum(Document.word_count))
        .where(Document.user_key == user_key, Document.status == DocumentStatus.INDEXED)
        .group_by(Document.kind)
    ).all()
    return {
        "by_kind": {row[0]: row[1] for row in rows},
        "total_documents": sum(row[1] for row in rows),
        "total_words": sum(row[2] or 0 for row in rows),
    }
