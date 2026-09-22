"""arq worker.

    arq app.workers.main.WorkerSettings

Schedule (UTC):
  every 4 hours  full crawl of every enabled source
  06:00          deadline reminders
  07:00          daily digest
  Mon 07:30      weekly digest
  03:30          expire past-deadline postings

The crawl runs at 01:00, 05:00, 09:00, 13:00, 17:00 and 21:00 — a four-hour
cadence. Deadlines move in days, not minutes, so anything tighter mostly
re-reads unchanged pages and burns goodwill with the sites being crawled.
Users who cannot wait have a manual refresh (POST /opportunities/refresh),
which is globally throttled rather than per-user.
"""

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.enums import DigestFrequency
from app.workers.tasks import (
    crawl_sources,
    expire_stale_opportunities,
    send_deadline_reminders,
    send_digests,
)


async def daily_digest(ctx: dict) -> dict:
    return await send_digests(ctx, DigestFrequency.DAILY)


async def weekly_digest(ctx: dict) -> dict:
    return await send_digests(ctx, DigestFrequency.WEEKLY)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [
        crawl_sources,
        send_deadline_reminders,
        send_digests,
        expire_stale_opportunities,
    ]
    cron_jobs = [
        cron(crawl_sources, hour={1, 5, 9, 13, 17, 21}, minute=0),
        cron(expire_stale_opportunities, hour=3, minute=30),
        cron(send_deadline_reminders, hour=6, minute=0),
        cron(daily_digest, hour=7, minute=0),
        cron(weekly_digest, weekday=0, hour=7, minute=30),
    ]
    max_jobs = 5
    job_timeout = 1800
