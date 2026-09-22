"""LinkedIn adapter — credential-gated by design.

LinkedIn has no open jobs API and its User Agreement prohibits scraping. There
are exactly two lawful routes, and both need access we cannot assume:

  1. LinkedIn Talent Solutions / Job Posting API under a signed partner
     agreement. Set LINKEDIN_PARTNER_ACCESS_TOKEN once approved.
  2. The member's own data, retrieved with their consent through an approved
     product. That still does not grant a jobs-search endpoint.

Until a token is configured this adapter reports itself as skipped rather than
falling back to scraping. The transformation logic below is complete, so
supplying a partner token is the only step needed to turn it on.
"""

import httpx

from app.agent.base import AdapterResult, RawOpportunity, SourceAdapter
from app.agent.http import build_client
from app.agent.normalize import clean_text
from app.core.config import settings
from app.models import Source

PARTNER_SEARCH_URL = "https://api.linkedin.com/rest/jobSearch"


class LinkedInAdapter(SourceAdapter):
    key = "linkedin"
    label = "LinkedIn (partner API)"
    requires_credentials = True

    def is_configured(self) -> bool:
        return bool(settings.linkedin_partner_access_token)

    async def fetch(self, source: Source) -> AdapterResult:
        if not self.is_configured():
            return AdapterResult(
                skipped=True,
                skip_reason=(
                    "LINKEDIN_PARTNER_ACCESS_TOKEN is not set. LinkedIn has no public jobs "
                    "API and scraping breaches their User Agreement, so this source stays "
                    "off until a Talent Solutions partner token is supplied."
                ),
            )

        config = source.config or {}
        params = {
            "keywords": config.get("keywords", "graduate research artificial intelligence"),
            "count": int(config.get("count", 25)),
        }
        if config.get("location_id"):
            params["locationId"] = config["location_id"]

        result = AdapterResult()
        async with build_client() as client:
            try:
                response = await client.get(
                    config.get("api_url", PARTNER_SEARCH_URL),
                    params=params,
                    headers={
                        "Authorization": f"Bearer {settings.linkedin_partner_access_token}",
                        "LinkedIn-Version": config.get("api_version", "202405"),
                        "X-Restli-Protocol-Version": "2.0.0",
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                result.warnings.append(f"LinkedIn partner API call failed: {exc}")
                return result

        for element in payload.get("elements", []):
            title = clean_text(element.get("title", {}).get("text") or element.get("title") or "")
            job_id = element.get("id") or element.get("entityUrn", "").split(":")[-1]
            if not title or not job_id:
                continue
            company = element.get("companyName") or (element.get("company") or {}).get("name")
            result.opportunities.append(
                RawOpportunity(
                    title=title,
                    url=f"https://www.linkedin.com/jobs/view/{job_id}",
                    description=clean_text(
                        (element.get("description") or {}).get("text", ""), 8000
                    ),
                    organization=clean_text(company or "") or None,
                    location=clean_text(element.get("formattedLocation", "")) or None,
                    country=config.get("country"),
                    opportunity_type=config.get("type_hint"),
                    external_id=str(job_id),
                    raw={"provider": "linkedin", "job_id": str(job_id)},
                )
            )
        return result
