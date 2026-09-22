import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import Notification, User
from app.schemas.common import Message, Page
from app.schemas.engagement import NotificationRead, NotificationSummary

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationRead])
def list_notifications(
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[NotificationRead]:
    base = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        base = base.where(Notification.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(
        items=[NotificationRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/summary", response_model=NotificationSummary)
def summary(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> NotificationSummary:
    total = (
        db.scalar(
            select(func.count()).select_from(Notification).where(Notification.user_id == user.id)
        )
        or 0
    )
    unread = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
        or 0
    )
    return NotificationSummary(unread=unread, total=total)


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationRead:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.flush()
    return NotificationRead.model_validate(notification)


@router.post("/read-all", response_model=Message)
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Message:
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    return Message(detail=f"{result.rowcount} notification(s) marked read.")
