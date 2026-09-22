"""Handshake adapter — credential-gated by design.

Handshake postings sit behind institutional SSO; there is no anonymous listing to
read. A school gets programmatic access through Handshake's partner/employer API
with an institution-scoped token. Set HANDSHAKE_API_TOKEN and
HANDSHAKE_INSTITUTION_ID once your institution issues them.

Where a user wants their own Handshake feed and no institutional token exists,
the supported pattern is a per-user connection: the student authorises access and
we pull only their visible postings. That belongs in a per-user credential store,
which is why this class stays a platform-level adapter and simply skips.
"""

import httpx

from app.agent.base import AdapterResult, RawOpportunity, SourceAdapter
from app.agent.http import build_client
from app.agent.normalize import clean_text
from app.core.config import settings
from app.models import Source

DEFAULT_API_URL = "https://app.joinhandshake.com/api/v1/jobs"


class HandshakeAdapter(SourceAdapter):
    key = "handshake"
    label = "Handshake (institutional API)"
    requires_credentials = True

    def is_configured(self) -> bool:
        return bool(settings.handshake_api_token)

    async def fetch(self, source: Source) -> AdapterResult:
        if not self.is_configured():
            return AdapterResult(
                skipped=True,
                skip_reason=(
                    "HANDSHAKE_API_TOKEN is not set. Handshake postings are gated behind "
                    "institutional SSO, so this source stays off until your school issues "
                    "an API token."
                ),
            )

        config = source.config or {}
        params = {
            "per_page": int(config.get("per_page", 50)),
            "page": int(config.get("page", 1)),
        }
        if settings.handshake_institution_id:
            params["institution_id"] = settings.handshake_institution_id
        if config.get("job_type"):
            params["job_type"] = config["job_type"]

        result = AdapterResult()
        async with build_client() as client:
            try:
                response = await client.get(
                    config.get("api_url", DEFAULT_API_URL),
                    params=params,
                    headers={"Authorization": f"Bearer {settings.handshake_api_token}"},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                result.warnings.append(f"Handshake API call failed: {exc}")
                return result

        for job in payload.get("jobs", payload.get("data", [])):
            title = clean_text(job.get("title", ""))
            job_id = job.get("id")
            if not title or not job_id:
                continue
            employer = job.get("employer") or {}
            result.opportunities.append(
                RawOpportunity(
                    title=title,
                    url=job.get("url") or f"https://app.joinhandshake.com/jobs/{job_id}",
                    description=clean_text(job.get("description", ""), 8000),
                    organization=clean_text(employer.get("name", "")) or None,
                    location=clean_text(job.get("location", "")) or None,
                    country=config.get("country"),
                    opportunity_type=config.get("type_hint"),
                    deadline_text=job.get("apply_start_date") and None,
                    external_id=str(job_id),
                    raw={"provider": "handshake", "job_id": str(job_id)},
                )
            )
        return result
