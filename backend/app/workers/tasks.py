"""Background jobs: the scheduled crawl, deadline reminders and email digests."""

from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import and_, or_, select

from app.agent.pipeline import run_all_sources
from app.core.db import SessionLocal
from app.core.enums import DigestFrequency, NotificationType, OpportunityStatus
from app.models import Notification, Opportunity, SavedOpportunity, User, UserPreference
from app.services.mailer import send_platform_email
from app.services.matching import matching_query
from app.services.notifications import notify

log = structlog.get_logger(__name__)


async def crawl_sources(ctx: dict, only_slug: str | None = None) -> dict:
    """Run every enabled source and announce new matches."""
    db = SessionLocal()
    try:
        reports = await run_all_sources(db, only_slug=only_slug)
        summary = {
            "sources": len(reports),
            "created": sum(r.created for r in reports),
            "updated": sum(r.updated for r in reports),
            "notified": sum(r.notified for r in reports),
            "skipped": [r.source_slug for r in reports if r.skipped],
        }
        log.info("crawl_complete", **summary)
        return summary
    finally:
        db.close()


async def send_deadline_reminders(ctx: dict) -> dict:
    """Remind users about saved opportunities whose deadline is approaching.

    The reminder windows are per-user (deadline_reminder_days), and a given
    (opportunity, window) pair only ever fires once.
    """
    db = SessionLocal()
    sent = 0
    try:
        rows = db.execute(
            select(SavedOpportunity, Opportunity, User)
            .join(Opportunity, Opportunity.id == SavedOpportunity.opportunity_id)
            .join(User, User.id == SavedOpportunity.user_id)
            .where(
                Opportunity.application_deadline.isnot(None),
                Opportunity.application_deadline >= date.today(),
                Opportunity.application_deadline <= date.today() + timedelta(days=30),
                User.is_active.is_(True),
                SavedOpportunity.status.notin_(["applied", "withdrawn", "rejected", "offer"]),
            )
        ).all()

        for _saved, opportunity, user in rows:
            preference = user.preference
            windows = (preference.deadline_reminder_days if preference else None) or [14, 7, 1]
            days_left = (opportunity.application_deadline - date.today()).days
            if days_left not in windows:
                continue

            marker = f"deadline:{opportunity.id}:{days_left}"
            already = db.scalar(
                select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.type == NotificationType.DEADLINE_REMINDER,
                    Notification.payload["marker"].astext == marker,
                )
            )
            if already:
                continue

            notify(
                db,
                user,
                NotificationType.DEADLINE_REMINDER,
                title=f"{days_left} day{'s' if days_left != 1 else ''} left: {opportunity.title}",
                body=(
                    f"Closes {opportunity.application_deadline.strftime('%d %B %Y')} · "
                    f"{opportunity.organization or 'Unknown organisation'}"
                ),
                link=f"/opportunities/{opportunity.id}",
                payload={"marker": marker, "opportunity_id": str(opportunity.id)},
                force_email=True,  # a deadline is time-critical, it bypasses digest batching
            )
            sent += 1

        db.commit()
        log.info("deadline_reminders_sent", count=sent)
        return {"reminders_sent": sent}
    finally:
        db.close()


def _build_digest(
    user: User, notifications: list[Notification], new_matches: list[Opportunity]
) -> tuple[str, str]:
    lines = [f"Hello {user.full_name or 'there'},", ""]
    if new_matches:
        lines.append(
            f"{len(new_matches)} new opportunit{'ies' if len(new_matches) != 1 else 'y'} matching your interests:"
        )
        lines.append("")
        for opportunity in new_matches[:12]:
            deadline = (
                opportunity.application_deadline.strftime("%d %b %Y")
                if opportunity.application_deadline
                else (opportunity.deadline_text or "no stated deadline")
            )
            lines.append(f"  • {opportunity.title}")
            lines.append(
                f"    {opportunity.organization or 'Unknown'} · "
                f"{opportunity.opportunity_type.replace('_', ' ')} · deadline {deadline}"
            )
            lines.append(f"    {opportunity.url}")
            lines.append("")
    other = [n for n in notifications if n.type != NotificationType.NEW_MATCH]
    if other:
        lines.append("Also waiting for you:")
        for notification in other[:10]:
            lines.append(f"  • {notification.title}")
        lines.append("")
    lines.append("--\nGradPortal · change your digest frequency in profile settings.")

    text = "\n".join(lines)
    items = "".join(
        f'<li style="margin-bottom:14px"><a href="{o.url}" style="color:#b75928;text-decoration:none">'
        f"<strong>{o.title}</strong></a><br>"
        f'<span style="color:#666666;font-size:13px">{o.organization or "Unknown"} · '
        f"{o.opportunity_type.replace('_', ' ')}</span></li>"
        for o in new_matches[:12]
    )
    html = f"""<!doctype html><html><body style="font-family:system-ui,sans-serif;background:#f6f8fa;padding:24px">
  <div style="max-width:600px;margin:0 auto;background:#fff;border:1px solid #e5e4e4;border-radius:8px;padding:28px">
    <h2 style="font-weight:300;font-size:28px;margin:0 0 6px;color:#000">Your opportunities</h2>
    <p style="color:#8d8d8d;font-size:13px;margin:0 0 20px">{len(new_matches)} new match(es)</p>
    <ul style="padding-left:18px;margin:0">{items}</ul>
    <hr style="border:0;border-top:1px solid #e5e4e4;margin:24px 0 12px">
    <p style="font-size:12px;color:#8d8d8d;margin:0">GradPortal · change your digest frequency in profile settings.</p>
  </div></body></html>"""
    return text, html


async def send_digests(ctx: dict, frequency: str = DigestFrequency.DAILY) -> dict:
    """Batch the period's unsent notifications into one email per user."""
    db = SessionLocal()
    window = timedelta(days=1 if frequency == DigestFrequency.DAILY else 7)
    since = datetime.now(UTC) - window
    sent = 0
    try:
        users = db.scalars(
            select(User)
            .join(UserPreference, UserPreference.user_id == User.id)
            .where(
                User.is_active.is_(True),
                UserPreference.email_notifications_enabled.is_(True),
                UserPreference.email_digest == frequency,
            )
        ).all()

        for user in users:
            pending = list(
                db.scalars(
                    select(Notification).where(
                        Notification.user_id == user.id,
                        Notification.created_at >= since,
                        Notification.email_sent_at.is_(None),
                        Notification.email_suppressed.is_(False),
                    )
                ).all()
            )
            new_matches = list(
                db.scalars(
                    matching_query(user.preference).where(
                        Opportunity.created_at >= since,
                        Opportunity.status == OpportunityStatus.PUBLISHED,
                        or_(
                            Opportunity.application_deadline.is_(None),
                            Opportunity.application_deadline >= date.today(),
                        ),
                    )
                )
                .unique()
                .all()
            )
            if not pending and not new_matches:
                continue

            text, html = _build_digest(user, pending, new_matches)
            subject = (
                f"{len(new_matches)} new opportunit{'ies' if len(new_matches) != 1 else 'y'} for you"
                if new_matches
                else "Your GradPortal update"
            )
            if send_platform_email(user.email, subject, text, html):
                stamp = datetime.now(UTC)
                for notification in pending:
                    notification.email_sent_at = stamp
                sent += 1

        db.commit()
        log.info("digests_sent", frequency=frequency, count=sent)
        return {"digests_sent": sent, "frequency": frequency}
    finally:
        db.close()


async def expire_stale_opportunities(ctx: dict) -> dict:
    """Mark past-deadline postings expired so they drop out of the default feed."""
    db = SessionLocal()
    try:
        stale = db.scalars(
            select(Opportunity).where(
                and_(
                    Opportunity.status == OpportunityStatus.PUBLISHED,
                    Opportunity.application_deadline.isnot(None),
                    Opportunity.application_deadline < date.today() - timedelta(days=1),
                )
            )
        ).all()
        for opportunity in stale:
            opportunity.status = OpportunityStatus.EXPIRED
        db.commit()
        log.info("opportunities_expired", count=len(stale))
        return {"expired": len(stale)}
    finally:
        db.close()
