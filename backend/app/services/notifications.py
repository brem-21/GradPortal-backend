"""In-app notifications, with an email copy when the user allows it.

Every notify() writes a Notification row (the in-app bell) and, if the user's
preferences allow it and the digest is set to instant, also sends the email copy.
Digest users get the same rows swept up by the worker's daily/weekly job.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import DigestFrequency, NotificationType
from app.models import Notification, User
from app.services.mailer import render_notification_email, send_platform_email

log = structlog.get_logger(__name__)


def notify(
    db: Session,
    user: User,
    type_: NotificationType,
    title: str,
    body: str | None = None,
    link: str | None = None,
    payload: dict | None = None,
    force_email: bool = False,
) -> Notification:
    notification = Notification(
        user_id=user.id,
        type=str(type_),
        # The column is varchar(255) and callers build titles from scraped
        # data. An over-long title used to abort the whole transaction that
        # created it — which meant one verbose course description could fail
        # an entire crawl.
        title=title[:255],
        body=body,
        link=link,
        payload=payload or {},
    )
    db.add(notification)
    db.flush()

    preference = user.preference
    emails_on = preference is None or preference.email_notifications_enabled
    digest = preference.email_digest if preference else DigestFrequency.INSTANT

    if not emails_on and not force_email:
        notification.email_suppressed = True
        return notification

    send_now = force_email or digest == DigestFrequency.INSTANT
    if send_now:
        text, html = render_notification_email(title, body, link)
        if send_platform_email(user.email, title, text, html):
            notification.email_sent_at = datetime.now(UTC)
        else:
            log.warning("notification_email_failed", user_id=str(user.id), title=title)

    return notification


def notify_many(
    db: Session,
    users: list[User],
    type_: NotificationType,
    title: str,
    body: str | None = None,
    link: str | None = None,
    payload: dict | None = None,
) -> int:
    for user in users:
        notify(db, user, type_, title, body, link, payload)
    return len(users)


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        or 0
    )
