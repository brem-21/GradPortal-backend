"""Admin-managed site content: background media and success stories.

Both were hardcoded in the frontend originally. They are content, not code —
an admin should be able to add a photograph or a new story without a deploy,
and the slideshow should grow as they do.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, uuid_pk


class MediaSlot:
    """Where a piece of media can appear.

    A slot is a place on the site, not a file: several assets share a slot and
    the slideshow rotates through them, which is what makes uploading one more
    image extend the rotation rather than replace anything.
    """

    HERO = "hero"
    CLOSING = "closing"
    MENTOR_CARD = "mentor_card"
    FOOTER = "footer"
    SIGNIN = "signin"
    COMMUNITY = "community"
    GALLERY = "gallery"

    ALL = (HERO, CLOSING, MENTOR_CARD, FOOTER, SIGNIN, COMMUNITY, GALLERY)

    LABELS = {
        HERO: "Landing hero",
        CLOSING: "Landing closing band",
        MENTOR_CARD: "Landing mentor card",
        FOOTER: "Footer",
        SIGNIN: "Sign-in page",
        COMMUNITY: "Overview community band",
        GALLERY: "Photo gallery strip",
    }


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_media_sha"),
        Index("ix_media_slots", "slots", postgresql_using="gin"),
        Index("ix_media_enabled_position", "enabled", "position"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)

    # A still, an animated GIF, or a silent video loop.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="image")
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    title: Mapped[str | None] = mapped_column(String(255))
    # Required: this is decorative background, but the gallery shows it as
    # content and a screen reader needs something.
    alt_text: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    credit: Mapped[str | None] = mapped_column(String(255))

    slots: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Per-asset scrim override; falls back to the slot default when null.
    overlay: Mapped[float | None] = mapped_column(Float)

    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    @property
    def url(self) -> str:
        return f"/media/{self.storage_path}"


class SuccessStory(Base, TimestampMixin):
    __tablename__ = "success_stories"
    __table_args__ = (Index("ix_stories_published_position", "published", "position"),)

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(255), nullable=False)
    field: Mapped[str | None] = mapped_column(String(64))
    quote: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional photograph of the person. Absent renders as a monogram.
    photo_path: Mapped[str | None] = mapped_column(Text)
    institution: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(100))
    link_url: Mapped[str | None] = mapped_column(Text)

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Record that the person agreed to be named and quoted. A story cannot be
    # published without it — an invented or unconsented testimonial presented as
    # genuine is deceptive advertising and a likeness problem.
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_note: Mapped[str | None] = mapped_column(Text)
    consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at_override: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def initials(self) -> str:
        parts = [p for p in (self.name or "").split() if p]
        return "".join(p[0].upper() for p in parts[:2]) or "?"

    @property
    def photo_url(self) -> str | None:
        return f"/media/{self.photo_path}" if self.photo_path else None


def _touch_consent(story: SuccessStory) -> None:
    if story.consent_confirmed and story.consent_recorded_at is None:
        story.consent_recorded_at = func.now()
