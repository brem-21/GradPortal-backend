import uuid
from datetime import datetime

from sqlalchemy import (
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

from eval_service.config import SCHEMA
from eval_service.db import Base


class RunStatus:
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Severity:
    STRENGTH = "strength"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"

    ALL = (STRENGTH, MINOR, MAJOR, CRITICAL)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("ix_runs_user_created", "user_key", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_key: Mapped[str] = mapped_column(String(320), nullable=False, index=True)

    track: Mapped[str] = mapped_column(String(16), nullable=False)
    target_field: Mapped[str | None] = mapped_column(String(64))
    target_programs: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(16), default=RunStatus.QUEUED, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    # Weighted mean of the per-document scores, 0-100.
    overall_score: Mapped[float | None] = mapped_column(Float)
    verdict: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(Text)
    committee_note: Mapped[str | None] = mapped_column(Text)
    priority_actions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    missing_documents: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )

    model: Mapped[str | None] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assessments: Mapped[list["DocumentAssessment"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="DocumentAssessment.created_at"
    )


class DocumentAssessment(Base):
    __tablename__ = "document_assessments"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Reference only — the document itself belongs to doc-service.
    document_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    document_title: Mapped[str] = mapped_column(String(500), nullable=False)

    rubric_label: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reasoning: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.COMPLETED, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[EvaluationRun] = relationship(back_populates="assessments")
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", order_by="Finding.position"
    )


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.document_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    criterion_key: Mapped[str] = mapped_column(String(64), nullable=False)
    criterion_label: Mapped[str] = mapped_column(String(128), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    # 0-5 on the rubric band.
    score: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A quote from the document, so the applicant can find what is being discussed.
    evidence: Mapped[str | None] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    assessment: Mapped[DocumentAssessment] = relationship(back_populates="findings")
