"""Provider dependency adapters for HTTP transports."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.project_knowledge.infrastructure.api_dependencies import (
    get_project_knowledge_db,
)
from app.services.integration_settings import IntegrationSettingsService


async def get_embedder(
    db: AsyncSession = Depends(get_project_knowledge_db),
):
    """The OpenRouter embedder, with the credential the SETTINGS PAGE stores.

    The embedder is infrastructure: it stays on OpenRouter whatever
    ``OPENROUTER_ENABLE`` says, because that flag only chooses which LLM answers
    a chat turn. Its key comes from the admin settings page
    (``integration_settings`` → OpenRouter), resolved exactly like every other
    embedder call site — the workers, the ingestion pipeline and the FAQ indexer
    all read it through ``resolve_openrouter``.

    Reading it from a process env var instead is what this used to do, and it is
    why an operator who set the key in the UI could still see a search-test
    endpoint fail with "no credential". FastAPI caches the session dependency,
    so this shares the request's existing session rather than opening a second.
    """
    openrouter = await IntegrationSettingsService(db).resolve_openrouter()
    from app.composition.project_knowledge import build_default_embedder

    return build_default_embedder(openrouter_api_key=openrouter.api_key)


__all__ = ["get_embedder"]
