import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.agent.normalize import content_hash
from app.api.deps import get_current_user, require_admin, require_contributor
from app.core.db import get_db
from app.core.enums import (
    ApplicationStatus,
    DegreeLevel,
    FieldOfStudy,
    FundingType,
    NotificationType,
    OpportunityStatus,
    OpportunityType,
    UserRole,
)
from app.core.regions import expand_regions, region_options
from app.models import (
    Opportunity,
    OpportunityContact,
    OutreachEmail,
    SavedOpportunity,
    Source,
    User,
)
from app.schemas.common import Message, Page
from app.schemas.opportunity import (
    ContactRead,
    OpportunityCreate,
    OpportunityRead,
    OpportunityUpdate,
    OverviewStats,
    SavedOpportunityRead,
    SavedOpportunityUpsert,
)
from app.services.matching import match_score, matching_query, users_matching
from app.services.notifications import notify, unread_count

router = APIRouter(tags=["opportunities"])


def _hydrate(
    opportunity: Opportunity,
    saved: SavedOpportunity | None = None,
) -> OpportunityRead:
    read = OpportunityRead.model_validate(opportunity)
    read.contacts = [ContactRead.model_validate(c) for c in opportunity.contacts]
    read.is_saved = saved is not None
    read.saved_status = ApplicationStatus(saved.status) if saved else None
    if opportunity.application_deadline:
        read.days_until_deadline = (opportunity.application_deadline - date.today()).days
    return read


def _saved_map(db: Session, user_id: uuid.UUID, ids: list[uuid.UUID]) -> dict:
    if not ids:
        return {}
    rows = db.scalars(
        select(SavedOpportunity).where(
            SavedOpportunity.user_id == user_id,
            SavedOpportunity.opportunity_id.in_(ids),
        )
    ).all()
    return {row.opportunity_id: row for row in rows}


def _apply_filters(
    query: Select,
    q: str | None,
    opportunity_types: list[OpportunityType],
    fields_of_study: list[FieldOfStudy],
    degree_levels: list[DegreeLevel],
    countries: list[str],
    regions: list[str],
    funding_types: list[FundingType],
    open_to_international: bool | None,
    has_contact: bool | None,
    deadline_before: date | None,
    deadline_after: date | None,
    include_expired: bool,
) -> Select:
    if q:
        pattern = f"%{q}%"
        query = query.where(
            or_(
                Opportunity.title.ilike(pattern),
                Opportunity.description.ilike(pattern),
                Opportunity.organization.ilike(pattern),
                Opportunity.department.ilike(pattern),
            )
        )
    if opportunity_types:
        query = query.where(Opportunity.opportunity_type.in_([str(t) for t in opportunity_types]))
    if fields_of_study:
        query = query.where(Opportunity.fields_of_study.overlap([str(f) for f in fields_of_study]))
    if degree_levels:
        query = query.where(Opportunity.degree_levels.overlap([str(d) for d in degree_levels]))
    # Explicit countries and expanded regions are unioned: picking "Europe" and
    # "Canada" means either, not both.
    wanted_countries = list(countries) + expand_regions(regions)
    if wanted_countries:
        query = query.where(
            or_(Opportunity.country.in_(wanted_countries), Opportunity.is_remote.is_(True))
        )
    if funding_types:
        query = query.where(Opportunity.funding_type.in_([str(f) for f in funding_types]))
    if open_to_international is not None:
        query = query.where(Opportunity.open_to_international.is_(open_to_international))
    if has_contact:
        query = query.where(
            Opportunity.id.in_(
                select(OpportunityContact.opportunity_id).where(
                    OpportunityContact.email.isnot(None)
                )
            )
        )
    if deadline_before:
        query = query.where(Opportunity.application_deadline <= deadline_before)
    if deadline_after:
        query = query.where(Opportunity.application_deadline >= deadline_after)
    if not include_expired:
        query = query.where(
            or_(
                Opportunity.application_deadline.is_(None),
                Opportunity.application_deadline >= date.today(),
            )
        )
    return query


@router.get("/opportunities", response_model=Page[OpportunityRead])
def list_opportunities(
    q: str | None = None,
    opportunity_types: list[OpportunityType] = Query(default=[]),
    fields_of_study: list[FieldOfStudy] = Query(default=[]),
    degree_levels: list[DegreeLevel] = Query(default=[]),
    countries: list[str] = Query(default=[]),
    regions: list[str] = Query(
        default=[],
        description=(
            "europe | united_kingdom | united_states | canada | "
            "australia_nz | asia | africa | middle_east"
        ),
    ),
    funding_types: list[FundingType] = Query(default=[]),
    open_to_international: bool | None = None,
    has_contact: bool | None = None,
    deadline_before: date | None = None,
    deadline_after: date | None = None,
    include_expired: bool = False,
    match_my_preferences: bool = False,
    sort: str = Query("deadline", pattern="^(deadline|newest|relevance)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[OpportunityRead]:
    base = (
        matching_query(user.preference)
        if match_my_preferences
        else select(Opportunity).where(Opportunity.status == OpportunityStatus.PUBLISHED)
    )
    base = _apply_filters(
        base,
        q,
        opportunity_types,
        fields_of_study,
        degree_levels,
        countries,
        regions,
        funding_types,
        open_to_international,
        has_contact,
        deadline_before,
        deadline_after,
        include_expired,
    )

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    query = base.options(selectinload(Opportunity.contacts))
    if sort == "newest":
        query = query.order_by(Opportunity.created_at.desc())
    elif sort == "deadline":
        # Nulls last: dated opportunities are the actionable ones.
        query = query.order_by(
            Opportunity.application_deadline.is_(None),
            Opportunity.application_deadline.asc(),
            Opportunity.created_at.desc(),
        )
    else:  # relevance — score in Python over a bounded, recent window
        query = query.order_by(Opportunity.created_at.desc()).limit(500)

    if sort == "relevance":
        rows = list(db.scalars(query).unique().all())
        rows.sort(key=lambda o: match_score(o, user.preference), reverse=True)
        window = rows[(page - 1) * page_size : page * page_size]
        total = min(total, len(rows))
    else:
        window = list(
            db.scalars(query.offset((page - 1) * page_size).limit(page_size)).unique().all()
        )

    saved = _saved_map(db, user.id, [o.id for o in window])
    return Page(
        items=[_hydrate(o, saved.get(o.id)) for o in window],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/opportunities/overview", response_model=OverviewStats)
def overview(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> OverviewStats:
    """The numbers on the post-login overview screen, all scoped to this user."""
    base = matching_query(user.preference).where(
        or_(
            Opportunity.application_deadline.is_(None),
            Opportunity.application_deadline >= date.today(),
        )
    )
    matching_total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    week_ago = date.today() - timedelta(days=7)
    new_this_week = (
        db.scalar(
            select(func.count()).select_from(
                base.where(func.date(Opportunity.created_at) >= week_ago).subquery()
            )
        )
        or 0
    )
    closing = (
        db.scalar(
            select(func.count()).select_from(
                base.where(
                    Opportunity.application_deadline.isnot(None),
                    Opportunity.application_deadline <= date.today() + timedelta(days=7),
                ).subquery()
            )
        )
        or 0
    )

    saved_count = (
        db.scalar(
            select(func.count())
            .select_from(SavedOpportunity)
            .where(SavedOpportunity.user_id == user.id)
        )
        or 0
    )
    applied_count = (
        db.scalar(
            select(func.count())
            .select_from(SavedOpportunity)
            .where(
                SavedOpportunity.user_id == user.id,
                SavedOpportunity.status.in_(
                    [
                        ApplicationStatus.APPLIED,
                        ApplicationStatus.INTERVIEW,
                        ApplicationStatus.OFFER,
                    ]
                ),
            )
        )
        or 0
    )
    emails_sent = (
        db.scalar(
            select(func.count()).select_from(OutreachEmail).where(OutreachEmail.user_id == user.id)
        )
        or 0
    )

    matching_ids = select(base.subquery().c.id)

    by_type_rows = db.execute(
        select(Opportunity.opportunity_type, func.count())
        .where(Opportunity.id.in_(matching_ids))
        .group_by(Opportunity.opportunity_type)
    ).all()

    by_field_rows = db.execute(
        select(func.unnest(Opportunity.fields_of_study).label("field"), func.count())
        .where(Opportunity.id.in_(matching_ids))
        .group_by("field")
    ).all()

    return OverviewStats(
        matching_opportunities=matching_total,
        new_this_week=new_this_week,
        closing_in_7_days=closing,
        saved_count=saved_count,
        applied_count=applied_count,
        unread_notifications=unread_count(db, user.id),
        emails_sent=emails_sent,
        by_type={row[0]: row[1] for row in by_type_rows},
        by_field={row[0]: row[1] for row in by_field_rows},
    )


# A crawl hits every configured source, so it is throttled globally rather than
# per user: ten students pressing refresh must not mean ten sweeps of the same
# admissions pages.
MANUAL_REFRESH_COOLDOWN = timedelta(minutes=15)


def _run_crawl_in_background() -> None:
    import asyncio

    from app.agent.pipeline import run_all_sources
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        asyncio.run(run_all_sources(db))
    finally:
        db.close()


@router.get("/opportunities/freshness")
def freshness(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """When the catalogue was last refreshed, and whether a manual run is allowed."""
    last_run = db.scalar(select(func.max(Source.last_run_at)))
    enabled = db.scalar(
        select(func.count()).select_from(Source).where(Source.enabled.is_(True))
    ) or 0

    now = datetime.now(UTC)
    age_seconds = int((now - last_run).total_seconds()) if last_run else None
    can_refresh = last_run is None or (now - last_run) > MANUAL_REFRESH_COOLDOWN
    retry_after = (
        0
        if can_refresh
        else int((MANUAL_REFRESH_COOLDOWN - (now - last_run)).total_seconds())
    )
    return {
        "last_refreshed_at": last_run.isoformat() if last_run else None,
        "age_seconds": age_seconds,
        "enabled_sources": enabled,
        "can_refresh": can_refresh,
        "retry_after_seconds": retry_after,
        "scheduled_every_hours": 4,
    }


@router.post("/opportunities/refresh")
def refresh_opportunities(
    background: BackgroundTasks,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Trigger a crawl now, so a user is never stuck looking at stale listings."""
    last_run = db.scalar(select(func.max(Source.last_run_at)))
    now = datetime.now(UTC)

    if last_run is not None and (now - last_run) <= MANUAL_REFRESH_COOLDOWN:
        wait = int((MANUAL_REFRESH_COOLDOWN - (now - last_run)).total_seconds())
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"The catalogue was refreshed {int((now - last_run).total_seconds() // 60)} "
                f"minute(s) ago. Try again in {wait // 60 + 1} minute(s)."
            ),
            headers={"Retry-After": str(wait)},
        )

    background.add_task(_run_crawl_in_background)
    return {
        "started": True,
        "detail": "Refreshing from every enabled source. This usually takes under a minute.",
    }


@router.get("/opportunities/facets")
def facets(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Filter options with live counts, so the UI never offers an empty filter."""
    published = Opportunity.status == OpportunityStatus.PUBLISHED
    countries = db.execute(
        select(Opportunity.country, func.count())
        .where(published, Opportunity.country.isnot(None))
        .group_by(Opportunity.country)
        .order_by(func.count().desc())
        .limit(60)
    ).all()
    types = db.execute(
        select(Opportunity.opportunity_type, func.count())
        .where(published)
        .group_by(Opportunity.opportunity_type)
    ).all()
    fields = db.execute(
        select(func.unnest(Opportunity.fields_of_study).label("field"), func.count())
        .where(published)
        .group_by("field")
    ).all()
    # Region counts are computed from the countries actually present, so the
    # UI never offers a region with nothing behind it.
    country_counts = {row[0]: row[1] for row in countries if row[0]}
    regions = []
    for option in region_options():
        total = sum(
            count
            for name, count in country_counts.items()
            if name in set(expand_regions([option["value"]]))
        )
        regions.append({**option, "count": total})

    return {
        "regions": regions,
        "opportunity_types": [{"value": v, "count": c} for v, c in types],
        "fields_of_study": [{"value": v, "count": c} for v, c in fields],
        "countries": [{"value": v, "count": c} for v, c in countries],
        "degree_levels": [{"value": str(d), "count": None} for d in DegreeLevel],
        "funding_types": [{"value": str(f), "count": None} for f in FundingType],
    }


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityRead)
def read_opportunity(
    opportunity_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OpportunityRead:
    opportunity = db.scalar(
        select(Opportunity)
        .options(selectinload(Opportunity.contacts))
        .where(Opportunity.id == opportunity_id)
    )
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    is_owner = opportunity.submitted_by_user_id == user.id
    if opportunity.status != OpportunityStatus.PUBLISHED and not (
        is_owner or user.role == UserRole.ADMIN
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    saved = db.scalar(
        select(SavedOpportunity).where(
            SavedOpportunity.user_id == user.id,
            SavedOpportunity.opportunity_id == opportunity_id,
        )
    )
    return _hydrate(opportunity, saved)


@router.post("/opportunities", response_model=OpportunityRead, status_code=status.HTTP_201_CREATED)
def create_opportunity(
    payload: OpportunityCreate,
    user: User = Depends(require_contributor),
    db: Session = Depends(get_db),
) -> OpportunityRead:
    """Mentors and community admins post opportunities.

    An admin's post publishes immediately; a mentor's goes to the review queue.
    """
    url = str(payload.url)
    digest = content_hash(payload.title, url, payload.organization)
    if db.scalar(select(Opportunity).where(Opportunity.content_hash == digest)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This opportunity is already on the platform.",
        )

    is_admin = user.role == UserRole.ADMIN
    opportunity = Opportunity(
        title=payload.title,
        description=payload.description,
        summary=payload.summary,
        opportunity_type=payload.opportunity_type,
        fields_of_study=[str(f) for f in payload.fields_of_study],
        degree_levels=[str(d) for d in payload.degree_levels],
        organization=payload.organization,
        department=payload.department,
        location=payload.location,
        country=payload.country,
        is_remote=payload.is_remote,
        funding_type=payload.funding_type,
        funding_amount=payload.funding_amount,
        open_to_international=payload.open_to_international,
        application_deadline=payload.application_deadline,
        deadline_text=payload.deadline_text,
        url=url,
        apply_url=str(payload.apply_url) if payload.apply_url else None,
        source_name=payload.source_name or (user.full_name or user.email),
        submitted_by_user_id=user.id,
        content_hash=digest,
        status=OpportunityStatus.PUBLISHED if is_admin else OpportunityStatus.PENDING_REVIEW,
    )
    db.add(opportunity)
    db.flush()

    for index, contact in enumerate(payload.contacts):
        db.add(
            OpportunityContact(
                opportunity_id=opportunity.id,
                name=contact.name,
                role=contact.role,
                email=contact.email,
                phone=contact.phone,
                department=contact.department,
                source_url=contact.source_url or url,
                confidence=1.0,  # human-entered
                verified=True,
                is_primary=contact.is_primary or index == 0,
            )
        )
    db.flush()
    db.refresh(opportunity)

    if is_admin:
        for recipient in users_matching(db, opportunity):
            notify(
                db,
                recipient,
                NotificationType.NEW_MATCH,
                title=f"New match: {opportunity.title}",
                body=f"Posted by {user.full_name or 'a community admin'}.",
                link=f"/opportunities/{opportunity.id}",
                payload={"opportunity_id": str(opportunity.id)},
            )
    else:
        notify(
            db,
            user,
            NotificationType.OPPORTUNITY_SUBMITTED,
            title="Submitted for review",
            body=f"'{opportunity.title}' is queued for a community admin to review.",
            link=f"/opportunities/{opportunity.id}",
            payload={"opportunity_id": str(opportunity.id)},
        )

    return _hydrate(opportunity)


@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityRead)
def update_opportunity(
    opportunity_id: uuid.UUID,
    payload: OpportunityUpdate,
    user: User = Depends(require_contributor),
    db: Session = Depends(get_db),
) -> OpportunityRead:
    opportunity = db.scalar(
        select(Opportunity)
        .options(selectinload(Opportunity.contacts))
        .where(Opportunity.id == opportunity_id)
    )
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    is_admin = user.role == UserRole.ADMIN
    if not is_admin and opportunity.submitted_by_user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit what you posted."
        )

    data = payload.model_dump(exclude_unset=True)
    if "status" in data and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can change status."
        )

    previous_status = opportunity.status
    for key, value in data.items():
        if key in {"url", "apply_url"} and value is not None:
            value = str(value)
        elif key in {"fields_of_study", "degree_levels"} and value is not None:
            value = [str(v) for v in value]
        setattr(opportunity, key, value)

    if "title" in data or "url" in data:
        opportunity.content_hash = content_hash(
            opportunity.title, opportunity.url, opportunity.organization
        )
    if "status" in data:
        opportunity.reviewed_by_user_id = user.id

    db.flush()

    approved = (
        previous_status != OpportunityStatus.PUBLISHED
        and opportunity.status == OpportunityStatus.PUBLISHED
    )
    if approved:
        if opportunity.submitted_by_user_id:
            submitter = db.get(User, opportunity.submitted_by_user_id)
            if submitter:
                notify(
                    db,
                    submitter,
                    NotificationType.OPPORTUNITY_APPROVED,
                    title="Your opportunity is live",
                    body=f"'{opportunity.title}' has been approved and published.",
                    link=f"/opportunities/{opportunity.id}",
                    payload={"opportunity_id": str(opportunity.id)},
                )
        for recipient in users_matching(db, opportunity):
            notify(
                db,
                recipient,
                NotificationType.NEW_MATCH,
                title=f"New match: {opportunity.title}",
                body=opportunity.summary,
                link=f"/opportunities/{opportunity.id}",
                payload={"opportunity_id": str(opportunity.id)},
            )

    return _hydrate(opportunity)


@router.delete("/opportunities/{opportunity_id}", response_model=Message)
def delete_opportunity(
    opportunity_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Message:
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    db.delete(opportunity)
    return Message(detail="Opportunity deleted.")


@router.get("/admin/opportunities/review-queue", response_model=Page[OpportunityRead])
def review_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Page[OpportunityRead]:
    base = select(Opportunity).where(Opportunity.status == OpportunityStatus.PENDING_REVIEW)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.options(selectinload(Opportunity.contacts))
            .order_by(Opportunity.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .unique()
        .all()
    )
    return Page(items=[_hydrate(o) for o in rows], total=total, page=page, page_size=page_size)


# ---------------- Saved / application tracker ----------------


@router.get("/saved", response_model=Page[SavedOpportunityRead])
def list_saved(
    saved_status: ApplicationStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[SavedOpportunityRead]:
    base = select(SavedOpportunity).where(SavedOpportunity.user_id == user.id)
    if saved_status:
        base = base.where(SavedOpportunity.status == saved_status)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.options(
                selectinload(SavedOpportunity.opportunity).selectinload(Opportunity.contacts)
            )
            .order_by(SavedOpportunity.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .unique()
        .all()
    )
    items = [
        SavedOpportunityRead(
            id=row.id,
            status=ApplicationStatus(row.status),
            notes=row.notes,
            created_at=row.created_at,
            opportunity=_hydrate(row.opportunity, row),
        )
        for row in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.put("/opportunities/{opportunity_id}/save", response_model=SavedOpportunityRead)
def save_opportunity(
    opportunity_id: uuid.UUID,
    payload: SavedOpportunityUpsert,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SavedOpportunityRead:
    opportunity = db.scalar(
        select(Opportunity)
        .options(selectinload(Opportunity.contacts))
        .where(Opportunity.id == opportunity_id)
    )
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    saved = db.scalar(
        select(SavedOpportunity).where(
            SavedOpportunity.user_id == user.id,
            SavedOpportunity.opportunity_id == opportunity_id,
        )
    )
    if saved is None:
        saved = SavedOpportunity(user_id=user.id, opportunity_id=opportunity_id)
        db.add(saved)
    saved.status = payload.status
    if payload.notes is not None:
        saved.notes = payload.notes
    db.flush()

    return SavedOpportunityRead(
        id=saved.id,
        status=ApplicationStatus(saved.status),
        notes=saved.notes,
        created_at=saved.created_at,
        opportunity=_hydrate(opportunity, saved),
    )


@router.delete("/opportunities/{opportunity_id}/save", response_model=Message)
def unsave_opportunity(
    opportunity_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Message:
    saved = db.scalar(
        select(SavedOpportunity).where(
            SavedOpportunity.user_id == user.id,
            SavedOpportunity.opportunity_id == opportunity_id,
        )
    )
    if saved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not saved")
    db.delete(saved)
    return Message(detail="Removed from your list.")
