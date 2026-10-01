"""Shared embedding helpers for batch-then-fallback patterns."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Type alias for a batch embedder callable.
BatchEmbedder = Callable[[list[str]], Awaitable[list[list[float]]]]


@runtime_checkable
class BatchEmbeddingProvider(Protocol):
    """Optional batch operation supported by an injected single-text embedder."""

    async def batch(self, texts: list[str]) -> list[list[float]]: ...


async def embed_with_fallback(
    embed_batch: BatchEmbedder,
    texts: list[str],
    *,
    label: str = "embedder",
) -> list[list[float]]:
    """Embed many texts; fall back to one-by-one on batch mismatch.

    Tries the batch callable first.  If the returned vector count doesn't
    match the input count, logs a warning and retries each text individually
    using the same callable (wrapping each as a single-item list).
    """
    vectors = await embed_batch(texts)
    if len(vectors) == len(texts):
        return vectors
    logger.warning(
        "%s batch returned %d vectors for %d texts; retrying one-by-one",
        label,
        len(vectors),
        len(texts),
    )
    fallback_vectors: list[list[float]] = []
    for text in texts:
        single = await embed_batch([text])
        if not single:
            raise RuntimeError(f"{label} returned no vector for single-text fallback")
        fallback_vectors.append(single[0])
    return fallback_vectors
