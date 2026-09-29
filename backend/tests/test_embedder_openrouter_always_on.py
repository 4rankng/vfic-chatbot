"""The OpenRouter embedder is ALWAYS on, and its key comes from the settings page.

Two rules this pins, both of which have bitten the knowledge pipeline:

1. ``OPENROUTER_ENABLE`` is a CHAT-provider switch (which LLM answers a turn).
   It must never switch the embedder off — retrieval is infrastructure, and a
   project that silently stops indexing is worse than a project that errors.
2. The credential is the admin settings page value
   (``IntegrationSettingsService.resolve_openrouter``), not a process env var.
   An operator who sets the key in the UI must not also have to edit a .env.
"""

from __future__ import annotations

import pytest

from app.graph.embedders import OpenRouterEmbedder, build_embedder


class _Settings:
    """Minimal settings double: the embedder only reads these two."""

    embedding_provider = "openrouter"
    embedding_dim = 3072
    openrouter_api_key = ""
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_embedding_model = "openai/text-embedding-3-large"
    openrouter_embedding_timeout = 60
    # The chat switch, OFF — the embedder must not care.
    openrouter_enable = False


@pytest.mark.asyncio
async def test_embedder_is_built_with_openrouter_enable_off() -> None:
    embedder = build_embedder(_Settings(), openrouter_api_key="sk-or-settings")

    assert isinstance(embedder, OpenRouterEmbedder)
    assert embedder.api_key == "sk-or-settings"


@pytest.mark.asyncio
async def test_embedder_does_not_require_the_enable_flag() -> None:
    off = build_embedder(_Settings(), openrouter_api_key="sk-or-settings")
    assert off.api_key == "sk-or-settings"

    class _Enabled(_Settings):
        openrouter_enable = True

    on = build_embedder(_Enabled(), openrouter_api_key="sk-or-settings")
    # Same credential either way: the flag is not an input to the embedder.
    assert on.api_key == off.api_key


@pytest.mark.asyncio
async def test_embedder_ignores_the_process_environment(monkeypatch) -> None:
    # The credential is the settings page's, not the shell's.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-from-env")
    monkeypatch.setenv("SILVERSEA_OPENROUTER_API_KEY", "sk-or-from-legacy-env")

    embedder = build_embedder(_Settings(), openrouter_api_key="sk-or-settings-page")

    assert embedder.api_key == "sk-or-settings-page"


@pytest.mark.asyncio
async def test_missing_credential_names_the_settings_page(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SILVERSEA_OPENROUTER_API_KEY", raising=False)
    embedder = build_embedder(_Settings(), openrouter_api_key="")

    with pytest.raises(RuntimeError, match="Settings page"):
        await embedder.batch(["x"])


def test_build_default_embedder_requires_the_settings_page_key() -> None:
    # The embedding config is keyword-only and required: the old signature made
    # the OpenRouter key optional, which is exactly how the env fallback crept in.
    from app.composition.project_knowledge import build_default_embedder
    from app.project_knowledge.domain.embedding import EmbeddingRuntimeConfig

    embedder = build_default_embedder(
        embedding=EmbeddingRuntimeConfig(
            provider="openrouter", openrouter_api_key="sk-or-settings"
        )
    )
    assert isinstance(embedder, OpenRouterEmbedder)

    with pytest.raises(TypeError):
        build_default_embedder()  # type: ignore[call-arg]
