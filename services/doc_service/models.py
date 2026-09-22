import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from doc_service.config import SCHEMA, settings
from doc_service.db import Base


class DocumentKind:
    CV = "cv"
    SOP = "sop"
    MOTIVATION_LETTER = "motivation_letter"
    RECOMMENDATION = "recommendation"
    TRANSCRIPT = "transcript"
    RESEARCH_PROPOSAL = "research_proposal"
    OTHER = "other"

    ALL = (
        CV,
        SOP,
        MOTIVATION_LETTER,
        RECOMMENDATION,
        TRANSCRIPT,
        RESEARCH_PROPOSAL,
        OTHER,
    )


class DocumentStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # The same file uploaded twice by one user is the same document.
        UniqueConstraint("user_key", "sha256", name="uq_document_user_sha"),
        Index("ix_documents_user_kind", "user_key", "kind"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Partition key. Email, matching core-api's account identity.
    user_key: Mapped[str] = mapped_column(String(320), index=True, nullable=False)

    kind: Mapped[str] = mapped_column(String(32), nullable=False, default=DocumentKind.OTHER)
    title: Mapped[str | None] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)

    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_count: Mapped[int | None] = mapped_column(Integer)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default=DocumentStatus.PENDING, nullable=False, index=True
    )
    error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_chunks_user_document", "user_key", "document_id"),
        # HNSW over cosine distance: the query path is always
        # "nearest neighbours for one user", filtered then ranked.
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised from the parent so every retrieval filters on one indexed
    # column — a user must never be able to reach another user's chunk.
    user_key: Mapped[str] = mapped_column(String(320), nullable=False, index=True)

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(255))

    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embedding_dimensions), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")
