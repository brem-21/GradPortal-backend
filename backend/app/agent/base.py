"""Contracts every ingestion adapter implements.

An adapter's only job is to turn one configured Source into a list of
RawOpportunity records. Normalisation, dedupe, contact enrichment and persistence
all happen downstream in pipeline.py, so adapters stay small and testable.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.models import Source


@dataclass(slots=True)
class RawContact:
    name: str | None = None
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    department: str | None = None
    source_url: str | None = None
    confidence: float = 0.5


@dataclass(slots=True)
class RawOpportunity:
    """Adapter output. Every field except title/url is best-effort."""

    title: str
    url: str
    description: str = ""
    summary: str | None = None
    opportunity_type: str | None = None
    fields_of_study: list[str] = field(default_factory=list)
    degree_levels: list[str] = field(default_factory=list)
    organization: str | None = None
    department: str | None = None
    location: str | None = None
    country: str | None = None
    is_remote: bool = False
    funding_type: str | None = None
    funding_amount: str | None = None
    open_to_international: bool | None = None
    application_deadline: date | None = None
    deadline_text: str | None = None
    posted_at: datetime | None = None
    apply_url: str | None = None
    external_id: str | None = None
    contacts: list[RawContact] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    # Set when the adapter already fetched the detail page, so the enricher can
    # mine it for contacts without a second request.
    detail_html: str | None = None


@dataclass(slots=True)
class AdapterResult:
    opportunities: list[RawOpportunity] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None


class SourceAdapter(ABC):
    """Base class for every ingestion source.

    key: registry identifier stored on Source.adapter
    requires_credentials: True means the adapter self-disables until configured
    """

    key: str = ""
    label: str = ""
    requires_credentials: bool = False

    @abstractmethod
    async def fetch(self, source: Source) -> AdapterResult:
        """Pull the current opportunity listing for this source."""

    def is_configured(self) -> bool:
        """Overridden by gated adapters to report whether credentials are present."""
        return True
