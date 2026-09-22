import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import FundingType, OpportunityStatus, SourceKind
from app.models.base import TimestampMixin, uuid_pk


class Source(Base, TimestampMixin):
    """A place the ingestion agent pulls from. One row per configured adapter target."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default=SourceKind.UNIVERSITY, nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)  # registry key
    base_url: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_credentials: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_status: Mapped[str | None] = mapped_column(String(32))
    last_run_message: Mapped[str | None] = mapped_column(Text)

    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="source")


class Opportunity(Base, TimestampMixin):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_opportunity_content_hash"),
        Index("ix_opportunities_deadline", "application_deadline"),
        Index("ix_opportunities_status_type", "status", "opportunity_type"),
        Index("ix_opportunities_fields", "fields_of_study", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str | None] = mapped_column(Text)

    opportunity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fields_of_study: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    degree_levels: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)

    organization: Mapped[str | None] = mapped_column(String(255), index=True)
    department: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(100), index=True)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    funding_type: Mapped[str] = mapped_column(String(32), default=FundingType.UNKNOWN)
    funding_amount: Mapped[str | None] = mapped_column(String(255))
    open_to_international: Mapped[bool | None] = mapped_column(Boolean)

    application_deadline: Mapped[date | None] = mapped_column(Date)
    deadline_text: Mapped[str | None] = mapped_column(String(255))  # "rolling", "varies by program"
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    url: Mapped[str] = mapped_column(Text, nullable=False)
    apply_url: Mapped[str | None] = mapped_column(Text)

    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), index=True
    )
    source_name: Mapped[str | None] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)

    status: Mapped[str] = mapped_column(
        String(32), default=OpportunityStatus.PUBLISHED, nullable=False, index=True
    )
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    review_note: Mapped[str | None] = mapped_column(Text)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    source: Mapped[Source | None] = relationship(back_populates="opportunities")
    contacts: Mapped[list["OpportunityContact"]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan"
    )


class OpportunityContact(Base, TimestampMixin):
    """The person to email about an opportunity: admissions officer, PI, scholarship
    coordinator. `confidence` reflects how the address was obtained."""

    __tablename__ = "opportunity_contacts"

    id: Mapped[uuid.UUID] = uuid_pk()
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(64))
    department: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    # 1.0 = published on the opportunity page itself, lower = inferred/department fallback
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    opportunity: Mapped[Opportunity] = relationship(back_populates="contacts")


class SavedOpportunity(Base, TimestampMixin):
    """A user's application tracker row."""

    __tablename__ = "saved_opportunities"
    __table_args__ = (UniqueConstraint("user_id", "opportunity_id", name="uq_saved_user_opp"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="saved", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    opportunity: Mapped[Opportunity] = relationship()
