import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from app.core.enums import (
    ApplicationStatus,
    DegreeLevel,
    FieldOfStudy,
    FundingType,
    OpportunityStatus,
    OpportunityType,
    SourceKind,
)


class ContactBase(BaseModel):
    name: str | None = None
    role: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    department: str | None = None
    source_url: str | None = None


class ContactCreate(ContactBase):
    is_primary: bool = False


class ContactRead(ContactBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    confidence: float
    is_primary: bool
    verified: bool


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    kind: SourceKind
    adapter: str
    base_url: str | None
    enabled: bool
    requires_credentials: bool
    last_run_at: datetime | None
    last_run_status: str | None
    last_run_message: str | None


class OpportunityBase(BaseModel):
    title: str = Field(max_length=500)
    description: str = ""
    summary: str | None = None
    opportunity_type: OpportunityType
    fields_of_study: list[FieldOfStudy] = Field(default_factory=list)
    degree_levels: list[DegreeLevel] = Field(default_factory=list)
    organization: str | None = None
    department: str | None = None
    location: str | None = None
    country: str | None = None
    is_remote: bool = False
    funding_type: FundingType = FundingType.UNKNOWN
    funding_amount: str | None = None
    open_to_international: bool | None = None
    application_deadline: date | None = None
    deadline_text: str | None = None
    url: HttpUrl
    apply_url: HttpUrl | None = None


class OpportunityCreate(OpportunityBase):
    """Used by mentors and community admins to upload an opportunity."""

    source_name: str | None = None
    contacts: list[ContactCreate] = Field(default_factory=list)


class OpportunityUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    summary: str | None = None
    opportunity_type: OpportunityType | None = None
    fields_of_study: list[FieldOfStudy] | None = None
    degree_levels: list[DegreeLevel] | None = None
    organization: str | None = None
    department: str | None = None
    location: str | None = None
    country: str | None = None
    is_remote: bool | None = None
    funding_type: FundingType | None = None
    funding_amount: str | None = None
    open_to_international: bool | None = None
    application_deadline: date | None = None
    deadline_text: str | None = None
    url: HttpUrl | None = None
    apply_url: HttpUrl | None = None
    status: OpportunityStatus | None = None
    review_note: str | None = None


class OpportunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    summary: str | None
    opportunity_type: OpportunityType
    fields_of_study: list[str]
    degree_levels: list[str]
    organization: str | None
    department: str | None
    location: str | None
    country: str | None
    is_remote: bool
    funding_type: FundingType
    funding_amount: str | None
    open_to_international: bool | None
    application_deadline: date | None
    deadline_text: str | None
    posted_at: datetime | None
    url: str
    apply_url: str | None
    source_name: str | None
    status: OpportunityStatus
    created_at: datetime

    contacts: list[ContactRead] = Field(default_factory=list)
    # Hydrated per-request for the signed-in user
    is_saved: bool = False
    saved_status: ApplicationStatus | None = None
    days_until_deadline: int | None = None


class OpportunityFilters(BaseModel):
    q: str | None = None
    opportunity_types: list[OpportunityType] = Field(default_factory=list)
    fields_of_study: list[FieldOfStudy] = Field(default_factory=list)
    degree_levels: list[DegreeLevel] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    funding_types: list[FundingType] = Field(default_factory=list)
    source_kinds: list[SourceKind] = Field(default_factory=list)
    open_to_international: bool | None = None
    has_contact: bool | None = None
    deadline_before: date | None = None
    deadline_after: date | None = None
    include_expired: bool = False
    sort: str = "deadline"  # deadline | newest | relevance


class SavedOpportunityUpsert(BaseModel):
    status: ApplicationStatus = ApplicationStatus.SAVED
    notes: str | None = None


class SavedOpportunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ApplicationStatus
    notes: str | None
    created_at: datetime
    opportunity: OpportunityRead


class OverviewStats(BaseModel):
    matching_opportunities: int
    new_this_week: int
    closing_in_7_days: int
    saved_count: int
    applied_count: int
    unread_notifications: int
    emails_sent: int
    by_type: dict[str, int]
    by_field: dict[str, int]
