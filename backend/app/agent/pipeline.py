"""The ingestion run: adapter output -> normalised, deduped, stored, announced.

Kept separate from the adapters so that every source gets identical treatment:
the same classifier, the same dedupe key, the same notification behaviour.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agent.base import RawOpportunity
from app.agent.contacts import extract_contacts_from_html
from app.agent.normalize import (
    classify_degrees,
    classify_fields_titled,
    classify_funding,
    classify_type,
    clean_text,
    content_hash,
    detect_international,
    extract_deadline,
    parse_date,
)
from app.agent.registry import get_adapter
from app.core.enums import NotificationType, OpportunityStatus
from app.models import Opportunity, OpportunityContact, Source
from app.services.matching import users_matching
from app.services.notifications import notify

log = structlog.get_logger(__name__)

# Only these five fields are in scope for the portal.
IN_SCOPE_REQUIRED = True


@dataclass
class RunReport:
    source_slug: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    skipped_out_of_scope: int = 0
    duplicates: int = 0
    notified: int = 0
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        if self.warnings and not self.fetched:
            return "error"
        if self.warnings:
            return "partial"
        return "ok"

    def as_dict(self) -> dict:
        return {
            "source": self.source_slug,
            "status": self.status,
            "fetched": self.fetched,
            "created": self.created,
            "updated": self.updated,
            "duplicates": self.duplicates,
            "skipped_out_of_scope": self.skipped_out_of_scope,
            "notified": self.notified,
            "warnings": self.warnings,
            "skip_reason": self.skip_reason,
        }


def normalise(raw: RawOpportunity, source: Source) -> dict | None:
    """Apply classifiers. Returns None when the posting is outside our five fields."""
    title = clean_text(raw.title, limit=500)
    description = clean_text(raw.description, limit=20000)
    blob_head = f"{title} {raw.summary or ''} {description[:4000]}"

    fields = raw.fields_of_study or classify_fields_titled(title, raw.summary, description)
    if IN_SCOPE_REQUIRED and not fields:
        return None

    opportunity_type = raw.opportunity_type or classify_type(title, raw.summary, description)
    degrees = raw.degree_levels or classify_degrees(blob_head)
    funding = raw.funding_type or classify_funding(blob_head)

    deadline = raw.application_deadline
    deadline_text = raw.deadline_text
    if deadline is None and deadline_text:
        deadline = parse_date(deadline_text)
    if deadline is None:
        deadline, parsed_text = extract_deadline(deadline_text, title, description)
        deadline_text = deadline_text or parsed_text

    international = raw.open_to_international
    if international is None:
        international = detect_international(description, title)

    return {
        "title": title,
        "description": description,
        "summary": clean_text(raw.summary or description, limit=280) or None,
        "opportunity_type": opportunity_type,
        "fields_of_study": fields,
        "degree_levels": degrees,
        "organization": clean_text(raw.organization, 255) or source.name,
        "department": clean_text(raw.department, 255) or None,
        "location": clean_text(raw.location, 255) or None,
        "country": clean_text(raw.country, 100) or None,
        "is_remote": raw.is_remote,
        "funding_type": funding,
        "funding_amount": clean_text(raw.funding_amount, 255) or None,
        "open_to_international": international,
        "application_deadline": deadline,
        "deadline_text": clean_text(deadline_text, 255) or None,
        "posted_at": raw.posted_at,
        "url": raw.url,
        "apply_url": raw.apply_url,
        "external_id": raw.external_id,
        "source_id": source.id,
        "source_name": source.name,
        "raw": raw.raw or {},
    }


def _sync_contacts(db: Session, opportunity: Opportunity, raw: RawOpportunity) -> None:
    contacts = raw.contacts
    if not contacts and raw.detail_html:
        contacts = extract_contacts_from_html(raw.detail_html, raw.url)
    if not contacts:
        return

    existing = {c.email.lower() for c in opportunity.contacts if c.email}
    ranked = sorted(contacts, key=lambda c: c.confidence, reverse=True)
    has_primary = any(c.is_primary for c in opportunity.contacts)

    for index, contact in enumerate(ranked):
        if not contact.email or contact.email.lower() in existing:
            continue
        db.add(
            OpportunityContact(
                opportunity_id=opportunity.id,
                name=contact.name,
                role=contact.role,
                email=contact.email,
                phone=contact.phone,
                department=contact.department,
                source_url=contact.source_url or raw.url,
                confidence=contact.confidence,
                is_primary=(index == 0 and not has_primary),
            )
        )
        existing.add(contact.email.lower())
        if index == 0:
            has_primary = True


def _announce(db: Session, opportunity: Opportunity) -> int:
    """Notify everyone whose saved preferences this new opportunity satisfies."""
    recipients = users_matching(db, opportunity)
    deadline = (
        opportunity.application_deadline.strftime("%d %B %Y")
        if opportunity.application_deadline
        else (opportunity.deadline_text or "no stated deadline")
    )
    for user in recipients:
        notify(
            db,
            user,
            NotificationType.NEW_MATCH,
            title=f"New match: {opportunity.title}",
            body=(
                f"{opportunity.organization or 'Unknown organisation'} · "
                f"{opportunity.opportunity_type.replace('_', ' ')} · Deadline: {deadline}"
            ),
            link=f"/opportunities/{opportunity.id}",
            payload={"opportunity_id": str(opportunity.id)},
        )
    return len(recipients)


async def run_source(db: Session, source: Source, announce: bool = True) -> RunReport:
    report = RunReport(source_slug=source.slug)
    adapter = get_adapter(source.adapter)

    if adapter is None:
        report.skipped = True
        report.skip_reason = f"Unknown adapter '{source.adapter}'"
    elif not source.enabled:
        report.skipped = True
        report.skip_reason = "Source is disabled"
    else:
        result = await adapter.fetch(source)
        report.warnings = result.warnings
        if result.skipped:
            report.skipped = True
            report.skip_reason = result.skip_reason
        else:
            report.fetched = len(result.opportunities)
            for raw in result.opportunities:
                payload = normalise(raw, source)
                if payload is None:
                    report.skipped_out_of_scope += 1
                    continue

                digest = content_hash(payload["title"], payload["url"], payload["organization"])
                existing = db.scalar(
                    select(Opportunity)
                    .options(selectinload(Opportunity.contacts))
                    .where(Opportunity.content_hash == digest)
                )

                if existing is not None:
                    changed = False
                    for key in (
                        "description",
                        "application_deadline",
                        "deadline_text",
                        "funding_type",
                    ):
                        value = payload[key]
                        if value and getattr(existing, key) != value:
                            setattr(existing, key, value)
                            changed = True
                    _sync_contacts(db, existing, raw)
                    if changed:
                        report.updated += 1
                    else:
                        report.duplicates += 1
                    continue

                opportunity = Opportunity(
                    **payload,
                    content_hash=digest,
                    status=OpportunityStatus.PUBLISHED,
                )
                db.add(opportunity)
                db.flush()
                _sync_contacts(db, opportunity, raw)
                report.created += 1
                if announce:
                    report.notified += _announce(db, opportunity)

    source.last_run_at = datetime.now(UTC)
    source.last_run_status = report.status
    source.last_run_message = report.skip_reason or "; ".join(report.warnings[:3]) or None
    db.flush()

    log.info("source_run_complete", **report.as_dict())
    return report


async def run_all_sources(db: Session, only_slug: str | None = None) -> list[RunReport]:
    query = select(Source).where(Source.enabled.is_(True))
    if only_slug:
        query = query.where(Source.slug == only_slug)
    reports = []
    for source in db.scalars(query).all():
        try:
            reports.append(await run_source(db, source))
        except Exception as exc:  # one bad source must not abort the sweep
            log.exception("source_run_failed", source=source.slug)
            source.last_run_at = datetime.now(UTC)
            source.last_run_status = "error"
            source.last_run_message = str(exc)[:500]
            reports.append(RunReport(source_slug=source.slug, warnings=[str(exc)[:500]]))
        db.commit()
    return reports


async def run_source_by_id(db: Session, source_id: uuid.UUID) -> RunReport:
    source = db.get(Source, source_id)
    if source is None:
        raise ValueError(f"No source with id {source_id}")
    report = await run_source(db, source)
    db.commit()
    return report
