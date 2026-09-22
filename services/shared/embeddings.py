"""Embeddings.

Served through OpenRouter by default, on the same key as chat — its
/api/v1/embeddings endpoint is OpenAI-compatible even though no embedding model
appears in the /models catalogue. Setting OPENAI_API_KEY routes to OpenAI
directly instead.

The interface is narrow on purpose: swapping to a local model or Voyage means
implementing `embed` and changing one setting, not touching call sites.
"""

import httpx
import structlog
import tiktoken
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from shared.config import EmbeddingSettings
from shared.errors import ProviderNotConfigured, UpstreamError

log = structlog.get_logger(__name__)

# text-embedding-3-* accept 8191 tokens; stay clear of the edge.
MAX_TOKENS_PER_INPUT = 8000
MAX_BATCH = 96


class EmbeddingClient:
    def __init__(self, settings: EmbeddingSettings) -> None:
        self.settings = settings
        self._encoder = tiktoken.get_encoding("cl100k_base")

    @property
    def configured(self) -> bool:
        return bool(self.settings.embeddings_api_key)

    @property
    def provider(self) -> str:
        return "openai" if self.settings.embeddings_use_openai_directly else "openrouter"

    @property
    def dimensions(self) -> int:
        return self.settings.embedding_dimensions

    @property
    def model(self) -> str:
        return self.settings.embeddings_model_id

    def count_tokens(self, text: str) -> int:
        return len(self._encoder.encode(text))

    def truncate(self, text: str) -> str:
        tokens = self._encoder.encode(text)
        if len(tokens) <= MAX_TOKENS_PER_INPUT:
            return text
        return self._encoder.decode(tokens[:MAX_TOKENS_PER_INPUT])

    @retry(
        retry=retry_if_exception_type(UpstreamError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self.configured:
            raise ProviderNotConfigured(
                "No embeddings key is set. Documents cannot be indexed or searched "
                "without one. Set OPENROUTER_API_KEY in services/.env (embeddings "
                "ride on the same key as chat) and restart."
            )

        headers = {
            "Authorization": f"Bearer {self.settings.embeddings_api_key}",
            "Content-Type": "application/json",
        }
        if not self.settings.embeddings_use_openai_directly:
            headers["HTTP-Referer"] = self.settings.openrouter_site_url
            headers["X-Title"] = self.settings.openrouter_app_name

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                response = await client.post(
                    f"{self.settings.embeddings_base_url}/embeddings",
                    headers=headers,
                    json={
                        "model": self.model,
                        "input": texts,
                        "dimensions": self.dimensions,
                    },
                )
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Embedding request failed: {exc}") from exc

        if response.status_code >= 400:
            raise UpstreamError(
                f"Embeddings ({self.provider}) returned "
                f"{response.status_code}: {response.text[:300]}"
            )

        payload = response.json()
        # The API may return items out of order; index is authoritative.
        items = sorted(payload["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in items]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        prepared = [self.truncate(text) if text.strip() else " " for text in texts]
        vectors: list[list[float]] = []
        for start in range(0, len(prepared), MAX_BATCH):
            batch = prepared[start : start + MAX_BATCH]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]
