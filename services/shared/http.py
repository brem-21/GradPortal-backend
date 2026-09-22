"""Typed client for calling another service.

Carries the caller's user token so the downstream service can authorise the same
person, plus the internal token for routes that browsers must never reach.
"""

from typing import Any

import httpx
import structlog

from shared.errors import UpstreamError

log = structlog.get_logger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class ServiceClient:
    def __init__(
        self,
        base_url: str,
        internal_token: str,
        service_name: str,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token
        self.service_name = service_name
        self.timeout = timeout or DEFAULT_TIMEOUT

    def _headers(self, user_token: str | None) -> dict[str, str]:
        headers = {"X-Internal-Token": self.internal_token}
        if user_token:
            headers["Authorization"] = f"Bearer {user_token}"
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict | None = None,
        user_token: str | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method, url, json=json, params=params, headers=self._headers(user_token)
                )
        except httpx.HTTPError as exc:
            log.warning("upstream_unreachable", service=self.service_name, url=url, error=str(exc))
            raise UpstreamError(
                f"{self.service_name} is unreachable. Is it running on {self.base_url}?"
            ) from exc

        if response.status_code >= 400:
            detail = response.text[:300]
            try:
                payload = response.json()
                detail = payload.get("detail", detail)
            except ValueError:
                pass
            log.warning(
                "upstream_error",
                service=self.service_name,
                url=url,
                status=response.status_code,
                detail=detail,
            )
            raise UpstreamError(f"{self.service_name} returned {response.status_code}: {detail}")

        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def get(self, path: str, **kwargs) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> Any:
        return await self.request("POST", path, **kwargs)
