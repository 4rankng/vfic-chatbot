"""Embedding transports (Gemini / OpenRouter) and the configured embedder.

Split out of ``clients.py`` so the embedding HTTP path — the highest-volume
outbound call in retrieval — sits beside its own transport rather than in the
module that carries the generation loop. Heavy SDKs stay imported lazily inside
the methods so importing this module is cheap and free of optional-dependency
failures at import time.

``clients.py`` re-exports these names, so ``from app.graph.clients import
build_embedder`` keeps working; the monkeypatched ``get_settings`` binding a
caller needs is the one on this module.
"""

from __future__ import annotations

from typing import Protocol

from app.core.config import get_settings


# The embedder is infrastructure, not an operator-facing provider switch: it
# rides the OpenRouter credential whatever ``OPENROUTER_ENABLE`` says (that flag
# only chooses which LLM answers a CHAT turn — see client_cache/factories).
#
# The credential itself belongs to the ADMIN SETTINGS PAGE — the
# ``openrouter_api_key`` row in ``integration_settings``, read through
# ``IntegrationSettingsService.resolve_openrouter``. It is deliberately NOT read
# from the process environment: an operator enabling OpenRouter in the UI must
# not also have to edit a .env for retrieval to start working. A caller that
# passes ``api_key`` already holds that settings-page value.
class BatchEmbedder(Protocol):
    """The slice of an embedding client the cached extraction bundle exposes.

    Both transports implement it, and the candidate-persistence path only ever
    calls ``batch``, so the bundle is typed to that capability rather than to a
    union a third provider would silently widen.
    """

    async def batch(self, texts: list[str]) -> list[list[float]]: ...


class GeminiEmbedder:
    def __init__(self, settings=None) -> None:
        self.s = settings or get_settings()
        self._client = None

    # Gemini's per-request token budget is shared across all inputs; large
    # batches silently truncate, returning fewer vectors than texts.  Chunk
    # into sub-batches so each request stays within limits and returns
    # exactly one vector per input.
    _EMBED_BATCH_SIZE = 100

    async def embed(self, text: str) -> list[float]:
        return (await self.batch([text]))[0]

    async def __call__(self, text: str) -> list[float]:
        return await self.embed(text)

    def _ensure_client(self):
        """The Gemini client, constructed once per instance on first use."""
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.s.gemini_api_key)
        return self._client

    async def _provider_call(self, chunk: list[str]):
        """One semaphore-bounded Gemini call for a chunk of texts."""
        from app.graph.llm_semaphore import get_embed_semaphore

        async with get_embed_semaphore():
            return await self._ensure_client().aio.models.embed_content(
                model=self.s.gemini_embedding_model,
                contents=chunk,
            )

    async def _embed_chunk(self, chunk: list[str]) -> list[list[float]]:
        """One provider call, returning exactly one vector per input text.

        An embedding whose ``values`` the SDK reports as ``None`` pads like an
        absent one rather than raising on ``list(None)``.
        """
        resp = await self._provider_call(chunk)
        dim = self.s.embedding_dim or 768
        # The SDK types its response as EmbedContentResponse | None, so a null
        # body is a real outcome, not a checker artifact. Treat it exactly like
        # an empty one: pad with zero vectors so the caller
        # (embed_with_fallback) can retry the texts one-by-one.
        embeddings = resp.embeddings if resp is not None else None
        if not embeddings:
            return [[0.0] * dim for _ in chunk]
        return [list(item.values) if item.values else [0.0] * dim for item in embeddings]

    async def batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts in chunked SDK calls.

        Gemini's per-request token budget is shared across the batch.  Sending
        all texts at once silently truncates, returning fewer vectors than
        texts.  This method chunks into sub-batches to stay within limits
        and guarantee one vector per input.
        """
        if not texts:
            return []
        if not self.s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for Gemini embeddings")
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), self._EMBED_BATCH_SIZE):
            chunk = texts[i : i + self._EMBED_BATCH_SIZE]
            all_vectors.extend(await self._embed_chunk(chunk))
        return all_vectors


class OpenRouterEmbedder:
    """OpenRouter embeddings client using the OpenAI-compatible embeddings API."""

    _EMBED_BATCH_SIZE = 96

    def __init__(
        self,
        settings=None,
        *,
        api_key: str | None = None,
    ) -> None:
        self.s = settings or get_settings()
        # No env lookup here on purpose: the key arrives from the settings page
        # (``api_key``) or from the configured default that backs it. The
        # embedder is never switched off by ``openrouter_enable``.
        self.api_key = (api_key or self.s.openrouter_api_key or "").strip()

    async def embed(self, text: str) -> list[float]:
        return (await self.batch([text]))[0]

    async def __call__(self, text: str) -> list[float]:
        return await self.embed(text)

    async def batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise RuntimeError(
                "OpenRouter embeddings need a credential. Set the OpenRouter API "
                "key on the admin Settings page (Cài đặt → tích hợp); "
                "OPENROUTER_ENABLE does not gate the embedder."
            )

        url = f"{self.s.openrouter_base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), self._EMBED_BATCH_SIZE):
            chunk = texts[i : i + self._EMBED_BATCH_SIZE]
            payload = {
                "model": self.s.openrouter_embedding_model,
                "input": chunk,
                "dimensions": self.s.embedding_dim,
            }
            # Reuse the process-scoped OpenRouter embedding client (Tech-Lead
            # Directive §4) — embedding calls are the highest-volume HTTP path
            # in retrieval, and per-call TLS handshakes were a measurable tax
            # on every RAG turn. Auth (Bearer) is passed per-request.
            from app.core.http import get_http_client

            client = await get_http_client(
                "openrouter_embed",
                timeout=self.s.openrouter_embedding_timeout,
                settings=self.s,
            )
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            body = resp.json()
            rows = sorted(body.get("data", []), key=lambda row: row.get("index", 0))
            if len(rows) != len(chunk):
                raise RuntimeError(
                    f"OpenRouter embeddings returned {len(rows)} vectors for {len(chunk)} inputs"
                )
            vectors = [row.get("embedding") for row in rows]
            if not all(isinstance(vector, list) and vector for vector in vectors):
                raise RuntimeError("OpenRouter embeddings response did not include vectors")
            all_vectors.extend([[float(value) for value in vector] for vector in vectors])
        return all_vectors


def build_embedder(
    settings=None,
    *,
    openrouter_api_key: str | None = None,
):
    """Build the configured embedding client."""
    s = settings or get_settings()
    provider = (s.embedding_provider or "openrouter").strip().lower()
    if provider == "openrouter":
        return OpenRouterEmbedder(s, api_key=openrouter_api_key)
    if provider == "gemini":
        return GeminiEmbedder(s)
    raise RuntimeError("EMBEDDING_PROVIDER must be 'openrouter' or 'gemini'")
