import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_service.config import SCHEMA
from rag_service.db import Base


class Role:
    USER = "user"
    ASSISTANT = "assistant"


class InputMode:
    TEXT = "text"
    VOICE = "voice"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_updated", "user_key", "updated_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_key: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="New conversation")
    # Scopes retrieval to specific documents when the user pins them.
    document_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), default=list, nullable=False
    )
    # Set when the conversation was opened from an opportunity page, so every
    # turn knows which posting is being discussed.
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    opportunity_title: Mapped[str | None] = mapped_column(String(500))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    input_mode: Mapped[str] = mapped_column(String(8), default=InputMode.TEXT, nullable=False)
    used_reasoning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Surfaced in the UI behind a disclosure, never mixed into the answer.
    reasoning: Mapped[str | None] = mapped_column(Text)
    # The queries the agent chose to run — shown so retrieval is inspectable.
    search_queries: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    grounded: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Web search ran for this turn. Costs ~3500x a plain call, so it is per-turn.
    used_web: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    model: Mapped[str | None] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    citations: Mapped[list["Citation"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="Citation.position"
    )
    web_sources: Mapped[list["WebSource"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="WebSource.position"
    )


class WebSource(Base):
    """A page the web-search plugin consulted for one answer.

    Kept separate from Citation: one points into the user's own documents, the
    other at the open internet, and the UI must not let them look alike.
    """

    __tablename__ = "web_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)

    message: Mapped["Message"] = relationship(back_populates="web_sources")


class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # References into doc-service. Snapshotted so a citation still renders if the
    # document is later deleted.
    document_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    chunk_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_title: Mapped[str] = mapped_column(String(500), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(255))
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    message: Mapped[Message] = relationship(back_populates="citations")
