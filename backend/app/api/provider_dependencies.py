"""Provider dependency adapters for HTTP transports."""

from app.composition.project_knowledge import build_default_embedder


def get_embedder():
    return build_default_embedder()

__all__ = ["get_embedder"]
