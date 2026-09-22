import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import DigestFrequency, UserRole
from app.models.base import TimestampMixin, uuid_pk


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default=UserRole.STUDENT, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    accounts: Mapped[list["OAuthAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    profile: Mapped["Profile | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    preference: Mapped["UserPreference | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class OAuthAccount(Base, TimestampMixin):
    """A linked identity provider. Holds the encrypted refresh token used to send
    mail on the user's behalf (Gmail / Microsoft Graph)."""

    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_oauth_provider_account"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # google | linkedin | azure-ad
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)

    user: Mapped[User] = relationship(back_populates="accounts")

    @property
    def can_send_mail(self) -> bool:
        send_scopes = {
            "https://www.googleapis.com/auth/gmail.send",
            "https://graph.microsoft.com/Mail.Send",
            "Mail.Send",
        }
        return self.refresh_token_encrypted is not None and bool(send_scopes & set(self.scopes))


class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )

    headline: Mapped[str | None] = mapped_column(String(255))
    bio: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    current_institution: Mapped[str | None] = mapped_column(String(255))
    current_title: Mapped[str | None] = mapped_column(String(255))

    linkedin_url: Mapped[str | None] = mapped_column(Text)
    github_url: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    cv_url: Mapped[str | None] = mapped_column(Text)

    # Applicant-side
    target_degree_level: Mapped[str | None] = mapped_column(String(32))
    target_intake: Mapped[str | None] = mapped_column(String(64))  # e.g. "Fall 2027"
    fields_of_study: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    gpa: Mapped[str | None] = mapped_column(String(32))
    test_scores: Mapped[str | None] = mapped_column(Text)  # free text: GRE 320, IELTS 7.5

    # Mentor-side
    is_mentor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mentor_is_accepting: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    years_experience: Mapped[int | None] = mapped_column(Integer)
    expertise: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    mentor_bio: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="profile")


class UserPreference(Base, TimestampMixin):
    """What the user picked at sign-up: the opportunity types and fields they want."""

    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )

    opportunity_types: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )
    fields_of_study: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    degree_levels: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    countries: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    # Region groups (europe, united_kingdom, ...) expanded at query time. Stored
    # separately from `countries` so the UI can round-trip "Europe" rather than
    # showing the thirty countries it expands to.
    regions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    funding_types: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)

    email_digest: Mapped[str] = mapped_column(
        String(16), default=DigestFrequency.DAILY, nullable=False
    )
    email_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deadline_reminder_days: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=lambda: [14, 7, 1], nullable=False
    )

    user: Mapped[User] = relationship(back_populates="preference")


Index("ix_profiles_is_mentor", Profile.is_mentor)
