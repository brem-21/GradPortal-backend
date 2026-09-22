import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.db import get_db
from app.core.enums import MentorshipStatus, NotificationType
from app.models import MentorshipRequest, User
from app.schemas.common import Page
from app.schemas.engagement import (
    MentorshipRequestCreate,
    MentorshipRequestRead,
    MentorshipRespond,
)
from app.services.notifications import notify

router = APIRouter(prefix="/mentorship", tags=["mentorship"])


@router.post("/requests", response_model=MentorshipRequestRead, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: MentorshipRequestCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MentorshipRequestRead:
    if payload.mentor_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot mentor yourself."
        )

    mentor = db.scalar(
        select(User).options(selectinload(User.profile)).where(User.id == payload.mentor_id)
    )
    if mentor is None or mentor.profile is None or not mentor.profile.is_mentor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mentor not found")
    if not mentor.profile.mentor_is_accepting:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This mentor is not taking new mentees right now.",
        )

    pending = db.scalar(
        select(MentorshipRequest).where(
            MentorshipRequest.mentee_id == user.id,
            MentorshipRequest.mentor_id == mentor.id,
            MentorshipRequest.status == MentorshipStatus.PENDING,
        )
    )
    if pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending request with this mentor.",
        )

    request = MentorshipRequest(
        mentee_id=user.id,
        mentor_id=mentor.id,
        topic=payload.topic,
        message=payload.message,
    )
    db.add(request)
    db.flush()

    notify(
        db,
        mentor,
        NotificationType.MENTORSHIP_REQUEST,
        title=f"Mentorship request from {user.full_name or user.email}",
        body=payload.topic or payload.message[:200],
        link="/mentorship",
        payload={"request_id": str(request.id), "mentee_id": str(user.id)},
    )

    db.refresh(request)
    return MentorshipRequestRead.model_validate(request)


@router.get("/requests", response_model=Page[MentorshipRequestRead])
def list_requests(
    role: str = Query("all", pattern="^(all|sent|received)$"),
    request_status: MentorshipStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[MentorshipRequestRead]:
    base = select(MentorshipRequest)
    if role == "sent":
        base = base.where(MentorshipRequest.mentee_id == user.id)
    elif role == "received":
        base = base.where(MentorshipRequest.mentor_id == user.id)
    else:
        base = base.where(
            or_(MentorshipRequest.mentee_id == user.id, MentorshipRequest.mentor_id == user.id)
        )
    if request_status:
        base = base.where(MentorshipRequest.status == request_status)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.options(selectinload(MentorshipRequest.mentee), selectinload(MentorshipRequest.mentor))
        .order_by(MentorshipRequest.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[MentorshipRequestRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/requests/{request_id}/respond", response_model=MentorshipRequestRead)
def respond(
    request_id: uuid.UUID,
    payload: MentorshipRespond,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MentorshipRequestRead:
    request = db.scalar(
        select(MentorshipRequest)
        .options(selectinload(MentorshipRequest.mentee), selectinload(MentorshipRequest.mentor))
        .where(MentorshipRequest.id == request_id)
    )
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if request.mentor_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the mentor can respond."
        )
    if payload.status not in {
        MentorshipStatus.ACCEPTED,
        MentorshipStatus.DECLINED,
        MentorshipStatus.COMPLETED,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid response status."
        )

    request.status = payload.status
    request.response_message = payload.response_message
    request.responded_at = datetime.now(UTC)
    db.flush()

    if payload.status in {MentorshipStatus.ACCEPTED, MentorshipStatus.DECLINED}:
        accepted = payload.status == MentorshipStatus.ACCEPTED
        notify(
            db,
            request.mentee,
            NotificationType.MENTORSHIP_ACCEPTED
            if accepted
            else NotificationType.MENTORSHIP_DECLINED,
            title=(
                f"{user.full_name or 'Your mentor'} accepted your mentorship request"
                if accepted
                else f"{user.full_name or 'The mentor'} declined your request"
            ),
            body=payload.response_message
            or (
                f"Reach out at {user.email}."
                if accepted
                else "They may be at capacity — try another mentor from the directory."
            ),
            link="/mentorship",
            payload={
                "request_id": str(request.id),
                "mentor_email": user.email if accepted else None,
            },
        )

    return MentorshipRequestRead.model_validate(request)


@router.get("/my-mentees", response_model=Page[MentorshipRequestRead])
def my_mentees(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[MentorshipRequestRead]:
    base = select(MentorshipRequest).where(
        MentorshipRequest.mentor_id == user.id,
        MentorshipRequest.status == MentorshipStatus.ACCEPTED,
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.options(selectinload(MentorshipRequest.mentee), selectinload(MentorshipRequest.mentor))
        .order_by(MentorshipRequest.responded_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[MentorshipRequestRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
