import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.db import get_db
from app.core.enums import NotificationType, OutreachStatus
from app.models import Opportunity, OpportunityContact, OutreachEmail, User
from app.schemas.common import Page
from app.schemas.engagement import (
    OutreachDraft,
    OutreachDraftRequest,
    OutreachRead,
    OutreachSendRequest,
)
from app.services.notifications import notify
from app.services.providers import MailSendError, pick_sending_account, send_as_user

router = APIRouter(prefix="/outreach", tags=["outreach"])

# A user cannot mail the same contact about the same opportunity twice in this window.
DUPLICATE_WINDOW_HOURS = 24
DAILY_SEND_LIMIT = 25


def _resolve_contact(
    db: Session, opportunity: Opportunity, contact_id: uuid.UUID | None
) -> OpportunityContact | None:
    if contact_id:
        contact = db.get(OpportunityContact, contact_id)
        if contact is None or contact.opportunity_id != opportunity.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That contact does not belong to this opportunity.",
            )
        return contact

    with_email = [c for c in opportunity.contacts if c.email]
    if not with_email:
        return None
    return max(with_email, key=lambda c: (c.is_primary, c.confidence))


def _compose(
    user: User, opportunity: Opportunity, contact: OpportunityContact | None
) -> tuple[str, str]:
    """Build a first draft from what the profile actually contains.

    Nothing is invented and nothing is bracketed: a line only appears when
    there is real content behind it. A draft peppered with "[your background
    here]" gets sent with the brackets still in it often enough that leaving
    them out is safer than prompting.
    """
    profile = user.profile
    name = user.full_name or user.email.split("@")[0]
    greeting = f"Dear {contact.name}," if contact and contact.name else "Dear Sir or Madam,"

    # Who they are, from the profile. Omitted entirely when unknown.
    standing_bits: list[str] = []
    if profile:
        if profile.current_title and profile.current_institution:
            standing_bits.append(f"{profile.current_title} at {profile.current_institution}")
        elif profile.current_institution:
            standing_bits.append(f"currently at {profile.current_institution}")
        elif profile.current_title:
            standing_bits.append(profile.current_title)
        if profile.target_degree_level:
            standing_bits.append(f"applying for {profile.target_degree_level} study")
        if profile.country:
            standing_bits.append(f"based in {profile.country}")
    standing = ", " + ", ".join(standing_bits) if standing_bits else ""

    subject = f"Enquiry — {opportunity.title}"
    if opportunity.organization:
        subject = f"Enquiry — {opportunity.title} ({opportunity.organization})"

    where = f" at {opportunity.organization}" if opportunity.organization else ""
    paragraphs = [
        greeting,
        f"My name is {name}{standing}. I am writing about the "
        f"{opportunity.title}{where}.",
    ]

    if opportunity.application_deadline:
        paragraphs.append(
            f"I note the application deadline is "
            f"{opportunity.application_deadline.strftime('%d %B %Y')}. I would be "
            "grateful for any guidance on the application requirements, and on "
            "whether the position remains open to new applicants."
        )
    else:
        paragraphs.append(
            "I would be grateful for any guidance on the application requirements, "
            "and on whether the position remains open to new applicants."
        )

    # Background, only if the profile carries something substantive.
    background = (profile.headline or profile.bio) if profile else None
    if background:
        paragraphs.append(background.strip())

    links = [f"Listing: {opportunity.url}"]
    if profile and profile.linkedin_url:
        links.append(f"LinkedIn: {profile.linkedin_url}")
    if profile and profile.cv_url:
        links.append(f"CV: {profile.cv_url}")
    paragraphs.append("\n".join(links))

    paragraphs.append("Thank you for your time. I look forward to hearing from you.")
    paragraphs.append(f"Kind regards,\n{name}\n{user.email}")

    return subject, "\n\n".join(paragraphs)


@router.post("/draft", response_model=OutreachDraft)
def draft_email(
    payload: OutreachDraftRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OutreachDraft:
    opportunity = db.scalar(
        select(Opportunity)
        .options(selectinload(Opportunity.contacts))
        .where(Opportunity.id == payload.opportunity_id)
    )
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    contact = _resolve_contact(db, opportunity, payload.contact_id)
    subject, body = _compose(user, opportunity, contact)

    account = pick_sending_account(list(user.accounts))
    blocked: str | None = None
    if account is None:
        blocked = (
            "Connect a Google or Microsoft mailbox to send from your own address. "
            "Sign out and sign back in with Google to grant send permission."
        )
    elif contact is None or not contact.email:
        blocked = "No contact address is on file for this opportunity yet."

    return OutreachDraft(
        to_email=contact.email if contact else None,
        to_name=contact.name if contact else None,
        subject=subject,
        body=body,
        can_send=blocked is None,
        send_blocked_reason=blocked,
        provider=account.provider if account else None,
    )


@router.post("/send", response_model=OutreachRead, status_code=status.HTTP_201_CREATED)
async def send_email(
    payload: OutreachSendRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OutreachRead:
    """Send from the user's own mailbox via their OAuth grant."""
    opportunity = db.scalar(
        select(Opportunity)
        .options(selectinload(Opportunity.contacts))
        .where(Opportunity.id == payload.opportunity_id)
    )
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    account = pick_sending_account(list(user.accounts))
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=(
                "No mailbox connected. Sign in with Google and grant send permission "
                "so the email comes from your own address."
            ),
        )

    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (
        db.scalar(
            select(func.count())
            .select_from(OutreachEmail)
            .where(
                OutreachEmail.user_id == user.id,
                OutreachEmail.created_at >= since,
                OutreachEmail.status == OutreachStatus.SENT,
            )
        )
        or 0
    )
    if sent_today >= DAILY_SEND_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily send limit of {DAILY_SEND_LIMIT} reached. This protects your address "
                "from being flagged as a bulk sender."
            ),
        )

    recent_duplicate = db.scalar(
        select(OutreachEmail).where(
            OutreachEmail.user_id == user.id,
            OutreachEmail.opportunity_id == opportunity.id,
            OutreachEmail.to_email == payload.to_email,
            OutreachEmail.status == OutreachStatus.SENT,
            OutreachEmail.created_at >= datetime.now(UTC) - timedelta(hours=DUPLICATE_WINDOW_HOURS),
        )
    )
    if recent_duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"You already emailed {payload.to_email} about this opportunity in the last "
                f"{DUPLICATE_WINDOW_HOURS} hours."
            ),
        )

    record = OutreachEmail(
        user_id=user.id,
        opportunity_id=opportunity.id,
        contact_id=payload.contact_id,
        from_email=user.email,
        to_email=payload.to_email,
        cc_emails=user.email if payload.cc_self else None,
        subject=payload.subject,
        body=payload.body,
        provider=account.provider,
        status=OutreachStatus.QUEUED,
    )
    db.add(record)
    db.flush()

    try:
        result = await send_as_user(
            account=account,
            from_email=user.email,
            from_name=user.full_name,
            to_email=payload.to_email,
            subject=payload.subject,
            body=payload.body,
            cc=[user.email] if payload.cc_self else None,
        )
    except MailSendError as exc:
        record.status = OutreachStatus.FAILED
        record.error = str(exc)[:1000]
        db.flush()
        notify(
            db,
            user,
            NotificationType.OUTREACH_FAILED,
            title="Email could not be sent",
            body=f"Sending to {payload.to_email} failed: {exc}",
            link=f"/opportunities/{opportunity.id}",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Send failed: {exc}"
        ) from exc

    record.status = OutreachStatus.SENT
    record.provider_message_id = result.message_id
    record.provider_thread_id = result.thread_id
    record.sent_at = datetime.now(UTC)

    if payload.contact_id:
        contact = db.get(OpportunityContact, payload.contact_id)
        if contact and not contact.verified:
            contact.verified = True  # a successful send is evidence the address resolves

    notify(
        db,
        user,
        NotificationType.OUTREACH_SENT,
        title=f"Email sent to {payload.to_email}",
        body=f"Re: {opportunity.title}",
        link=f"/opportunities/{opportunity.id}",
        payload={"opportunity_id": str(opportunity.id)},
    )
    db.flush()
    return OutreachRead.model_validate(record)


@router.get("", response_model=Page[OutreachRead])
def list_outreach(
    opportunity_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[OutreachRead]:
    base = select(OutreachEmail).where(OutreachEmail.user_id == user.id)
    if opportunity_id:
        base = base.where(OutreachEmail.opportunity_id == opportunity_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(OutreachEmail.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[OutreachRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
