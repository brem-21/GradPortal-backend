import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.enums import MentorshipStatus, NotificationType, OutreachStatus


class OutreachDraftRequest(BaseModel):
    """Ask the API for a prefilled email body for this opportunity + contact."""

    opportunity_id: uuid.UUID
    contact_id: uuid.UUID | None = None


class OutreachDraft(BaseModel):
    to_email: EmailStr | None
    to_name: str | None
    subject: str
    body: str
    can_send: bool
    send_blocked_reason: str | None = None
    provider: str | None = None


class OutreachSendRequest(BaseModel):
    opportunity_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    to_email: EmailStr
    cc_self: bool = True
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)


class OutreachRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    opportunity_id: uuid.UUID | None
    from_email: EmailStr
    to_email: EmailStr
    subject: str
    body: str
    provider: str
    status: OutreachStatus
    error: str | None
    sent_at: datetime | None
    created_at: datetime


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: NotificationType
    title: str
    body: str | None
    link: str | None
    payload: dict
    read_at: datetime | None
    created_at: datetime


class NotificationSummary(BaseModel):
    unread: int
    total: int


class MentorshipRequestCreate(BaseModel):
    mentor_id: uuid.UUID
    topic: str | None = None
    message: str = Field(min_length=10, max_length=4000)


class MentorshipRespond(BaseModel):
    status: MentorshipStatus
    response_message: str | None = None


class MentorshipPartner(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str | None
    email: EmailStr
    avatar_url: str | None


class MentorshipRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    topic: str | None
    message: str
    status: MentorshipStatus
    response_message: str | None
    responded_at: datetime | None
    created_at: datetime
    mentee: MentorshipPartner
    mentor: MentorshipPartner
