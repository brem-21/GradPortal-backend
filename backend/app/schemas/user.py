import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.enums import DigestFrequency, UserRole


class ProfileBase(BaseModel):
    headline: str | None = None
    bio: str | None = None
    country: str | None = None
    city: str | None = None
    current_institution: str | None = None
    current_title: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    website_url: str | None = None
    cv_url: str | None = None
    target_degree_level: str | None = None
    target_intake: str | None = None
    fields_of_study: list[str] = Field(default_factory=list)
    gpa: str | None = None
    test_scores: str | None = None
    is_mentor: bool = False
    mentor_is_accepting: bool = True
    years_experience: int | None = None
    expertise: list[str] = Field(default_factory=list)
    mentor_bio: str | None = None


class ProfileUpdate(ProfileBase):
    # Lives on User, not Profile, but the profile screen is where people edit it.
    avatar_url: str | None = None


class ProfileRead(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    updated_at: datetime


class PreferenceBase(BaseModel):
    opportunity_types: list[str] = Field(default_factory=list)
    fields_of_study: list[str] = Field(default_factory=list)
    degree_levels: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(
        default_factory=list,
        description=(
            "Region groups: europe, united_kingdom, united_states, canada, australia_nz, "
            "asia, africa, middle_east"
        ),
    )
    funding_types: list[str] = Field(default_factory=list)
    email_digest: DigestFrequency = DigestFrequency.DAILY
    email_notifications_enabled: bool = True
    deadline_reminder_days: list[int] = Field(default_factory=lambda: [14, 7, 1])


class PreferenceUpdate(PreferenceBase):
    pass


class PreferenceRead(PreferenceBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    avatar_url: str | None
    role: UserRole
    onboarding_completed: bool
    created_at: datetime


class MeRead(UserRead):
    profile: ProfileRead | None = None
    preference: PreferenceRead | None = None
    can_send_email_as_self: bool = False
    unread_notifications: int = 0


class OnboardingPayload(BaseModel):
    """Submitted right after first sign-in: what are you looking for?"""

    opportunity_types: list[str] = Field(min_length=1)
    fields_of_study: list[str] = Field(min_length=1)
    degree_levels: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    funding_types: list[str] = Field(default_factory=list)
    email_digest: DigestFrequency = DigestFrequency.DAILY
    # Required: a face on the profile is what makes a cold enquiry and a
    # mentorship request read as coming from a real person.
    avatar_url: str = Field(min_length=1, description="Provider picture or a URL the user supplies")
    # Optional profile seed
    headline: str | None = None
    country: str | None = None
    current_institution: str | None = None
    join_as_mentor: bool = False
    years_experience: int | None = None
    expertise: list[str] = Field(default_factory=list)


class MentorCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    full_name: str | None
    avatar_url: str | None
    headline: str | None
    country: str | None
    current_institution: str | None
    current_title: str | None
    years_experience: int | None
    expertise: list[str]
    mentor_bio: str | None
    linkedin_url: str | None
    mentor_is_accepting: bool


class OAuthAccountUpsert(BaseModel):
    """Posted by the Next.js auth callback so the API can store provider tokens."""

    provider: str
    provider_account_id: str
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)


class ProviderProfile(BaseModel):
    """Profile claims an OIDC provider returned at sign-in.

    Both Google and LinkedIn implement plain OpenID Connect, which carries
    name, picture, email and locale — and nothing else. Headline, positions and
    education need LinkedIn's `r_basicprofile` product, which is partner-gated,
    so those fields stay user-entered.
    """

    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None
    locale: str | None = None
    email_verified: bool | None = None


class SessionSyncPayload(BaseModel):
    email: EmailStr
    full_name: str | None = None
    avatar_url: str | None = None
    provider_profile: ProviderProfile | None = None
    account: OAuthAccountUpsert | None = None


class ConnectionRead(BaseModel):
    """One linked identity provider, and what it can actually do."""

    provider: str
    provider_account_id: str
    scopes: list[str]
    connected_at: datetime
    expires_at: datetime | None
    has_refresh_token: bool
    can_send_mail: bool
    # Why it cannot send, when it cannot. Empty when it can.
    blocked_reason: str | None = None


class ConnectionsRead(BaseModel):
    connections: list[ConnectionRead]
    can_send_email_as_self: bool
    sending_provider: str | None
