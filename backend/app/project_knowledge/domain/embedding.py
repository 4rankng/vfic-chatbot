"""Embedding runtime configuration shared by settings, composition and the
knowledge application layer.

Lives in the knowledge domain (not the settings service) because the provider
factory contract in ``project_knowledge.application.providers`` types its
``embedder`` factory with it, and that layer may not import from services.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingRuntimeConfig:
    """Which embedder the app builds, with the credential that backs it."""

    provider: str = "openrouter"
    openrouter_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_embedding_model: str = ""
