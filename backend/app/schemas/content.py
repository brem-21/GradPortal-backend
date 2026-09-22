import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MediaAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    kind: str
    width: int | None
    height: int | None
    title: str | None
    alt_text: str
    credit: str | None
    slots: list[str]
    position: int
    enabled: bool
    overlay: float | None
    url: str
    created_at: datetime


class MediaAssetList(BaseModel):
    items: list[MediaAssetRead]
    total: int


class MediaAssetUpdate(BaseModel):
    title: str | None = None
    alt_text: str | None = None
    credit: str | None = None
    slots: list[str] | None = None
    position: int | None = None
    enabled: bool | None = None
    overlay: float | None = Field(default=None, ge=0.0, le=1.0)


class SlotOption(BaseModel):
    value: str
    label: str
    asset_count: int


class Slide(BaseModel):
    """One slide as the frontend consumes it."""

    id: uuid.UUID
    src: str
    poster: str | None
    kind: str
    alt: str
    credit: str | None
    overlay: float | None


class SlideSet(BaseModel):
    slot: str
    label: str
    slides: list[Slide]
    interval_ms: int
    overlay: float


class SiteMedia(BaseModel):
    """Everything the public pages need, in one call."""

    sets: dict[str, SlideSet]
    gallery: list[Slide]


class SuccessStoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    outcome: str
    field: str | None
    quote: str
    institution: str | None
    country: str | None
    link_url: str | None
    photo_url: str | None
    initials: str
    position: int
    published: bool
    consent_confirmed: bool
    consent_note: str | None
    created_at: datetime


class SuccessStoryPublic(BaseModel):
    """What anonymous visitors see — no consent bookkeeping."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    outcome: str
    field: str | None
    quote: str
    institution: str | None
    country: str | None
    link_url: str | None
    photo_url: str | None
    initials: str


class SuccessStoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    outcome: str = Field(min_length=1, max_length=255)
    quote: str = Field(min_length=10, max_length=2000)
    field: str | None = None
    institution: str | None = None
    country: str | None = None
    link_url: str | None = None
    photo_path: str | None = None
    position: int = 0
    published: bool = False
    consent_confirmed: bool = False
    consent_note: str | None = None


class SuccessStoryUpdate(BaseModel):
    name: str | None = None
    outcome: str | None = None
    quote: str | None = None
    field: str | None = None
    institution: str | None = None
    country: str | None = None
    link_url: str | None = None
    photo_path: str | None = None
    position: int | None = None
    published: bool | None = None
    consent_confirmed: bool | None = None
    consent_note: str | None = None


class SuccessStoryList(BaseModel):
    items: list[SuccessStoryRead]
    total: int
