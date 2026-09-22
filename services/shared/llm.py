"""OpenRouter chat client.

Deliberately a thin httpx wrapper rather than a vendor SDK: OpenRouter is
OpenAI-compatible REST, and keeping the surface small is what lets the model
choice (and eventually the provider) be a config change.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from shared.config import OpenRouterSettings
from shared.errors import ProviderNotConfigured, UpstreamError

log = structlog.get_logger(__name__)


@dataclass
class WebCitation:
    """A source the web-search plugin actually consulted."""

    title: str
    url: str
    content: str | None = None


@dataclass
class ChatResult:
    content: str
    model: str
    # Reasoning models expose their chain separately; we surface it so the UI can
    # show "how it thought" without polluting the answer text.
    reasoning: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Populated when web search ran. Empty otherwise.
    web_citations: list[WebCitation] = field(default_factory=list)
    cost: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class OpenRouterClient:
    def __init__(self, settings: OpenRouterSettings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.openrouter_api_key)

    def model_for(self, reasoning: bool) -> str:
        return (
            self.settings.openrouter_reasoning_model
            if reasoning
            else self.settings.openrouter_default_model
        )

    def _headers(self) -> dict[str, str]:
        if not self.configured:
            raise ProviderNotConfigured(
                "OPENROUTER_API_KEY is not set, so chat and evaluation are unavailable. "
                "Add it to services/.env and restart."
            )
        return {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            # OpenRouter uses these for attribution on their dashboard.
            "HTTP-Referer": self.settings.openrouter_site_url,
            "X-Title": self.settings.openrouter_app_name,
        }

    def _payload(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        stream: bool,
        web_search: bool = False,
        web_max_results: int = 4,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if web_search:
            # Roughly 3500x the cost of a plain call, so this is never implicit —
            # the caller opts in per request.
            payload["plugins"] = [{"id": "web", "max_results": web_max_results}]
        return payload

    @staticmethod
    def _citations(message: dict[str, Any]) -> list[WebCitation]:
        citations: list[WebCitation] = []
        for annotation in message.get("annotations") or []:
            if annotation.get("type") != "url_citation":
                continue
            entry = annotation.get("url_citation") or {}
            url = entry.get("url")
            if not url:
                continue
            citations.append(
                WebCitation(
                    title=(entry.get("title") or url)[:300],
                    url=url,
                    content=(entry.get("content") or None),
                )
            )
        return citations

    @retry(
        retry=retry_if_exception_type(UpstreamError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        reasoning: bool = False,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
        web_search: bool = False,
        web_max_results: int = 4,
    ) -> ChatResult:
        chosen = model or self.model_for(reasoning)
        payload = self._payload(
            messages,
            chosen,
            temperature,
            max_tokens,
            json_mode,
            False,
            web_search,
            web_max_results,
        )

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
                response = await client.post(
                    f"{self.settings.openrouter_base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise UpstreamError(f"OpenRouter request failed: {exc}") from exc

        if response.status_code >= 400:
            raise UpstreamError(
                f"OpenRouter returned {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}

        return ChatResult(
            content=(message.get("content") or "").strip(),
            model=data.get("model", chosen),
            reasoning=message.get("reasoning"),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            web_citations=self._citations(message),
            cost=usage.get("cost"),
            raw=data,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        reasoning: bool = False,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        web_search: bool = False,
        web_max_results: int = 4,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield events as they arrive.

        Event shapes:
          {"type": "reasoning", "text": ...}   a reasoning-model chain fragment
          {"type": "content",   "text": ...}   an answer fragment
          {"type": "citations", "items": [...]} web sources, once they arrive
          {"type": "done",      "model": ...}
        """
        chosen = model or self.model_for(reasoning)
        payload = self._payload(
            messages,
            chosen,
            temperature,
            max_tokens,
            False,
            True,
            web_search,
            web_max_results,
        )

        seen_citations = False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
                async with client.stream(
                    "POST",
                    f"{self.settings.openrouter_base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode()[:300]
                        raise UpstreamError(f"OpenRouter returned {response.status_code}: {body}")

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        chunk = line.removeprefix("data: ").strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            parsed = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue

                        choice = (parsed.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}

                        if delta.get("reasoning"):
                            yield {"type": "reasoning", "text": delta["reasoning"]}
                        if delta.get("content"):
                            yield {"type": "content", "text": delta["content"]}

                        # Annotations may land on the delta or on the finished
                        # message, depending on the upstream provider.
                        if not seen_citations:
                            citations = self._citations(delta) or self._citations(
                                choice.get("message") or {}
                            )
                            if citations:
                                seen_citations = True
                                yield {
                                    "type": "citations",
                                    "items": [
                                        {"title": c.title, "url": c.url} for c in citations
                                    ],
                                }
        except httpx.HTTPError as exc:
            raise UpstreamError(f"OpenRouter stream failed: {exc}") from exc

        yield {"type": "done", "model": chosen}


def extract_json(text: str) -> dict[str, Any]:
    """Recover a JSON object from a model response.

    Even in JSON mode, reasoning models routinely wrap output in prose or fences,
    so parsing has to tolerate that rather than fail the whole evaluation.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text.removeprefix("```")
        text = text.removeprefix("json").strip()
        text = text.split("```")[0].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise UpstreamError(f"Model did not return usable JSON: {exc}") from exc
    raise UpstreamError("Model did not return JSON at all.")
