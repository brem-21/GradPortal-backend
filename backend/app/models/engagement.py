import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import MentorshipStatus, OutreachStatus
from app.models.base import TimestampMixin, uuid_pk
from app.models.user import User


class OutreachEmail(Base, TimestampMixin):
    """An email a user sent to an opportunity contact, from their own mailbox."""

    __tablename__ = "outreach_emails"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="SET NULL"), index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("opportunity_contacts.id", ondelete="SET NULL")
    )

    from_email: Mapped[str] = mapped_column(String(320), nullable=False)
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    cc_emails: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # google | microsoft | smtp
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    provider_thread_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default=OutreachStatus.QUEUED, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "read_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_suppressed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MentorshipRequest(Base, TimestampMixin):
    __tablename__ = "mentorship_requests"
    __table_args__ = (Index("ix_mentorship_mentor_status", "mentor_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    mentee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mentor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=MentorshipStatus.PENDING, nullable=False
    )
    response_message: Mapped[str | None] = mapped_column(Text)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    mentee: Mapped[User] = relationship(foreign_keys=[mentee_id])
    mentor: Mapped[User] = relationship(foreign_keys=[mentor_id])
