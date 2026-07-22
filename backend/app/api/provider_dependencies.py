"""FastAPI provider dependencies."""


def get_embedder():
    """Return the configured embedder without widening the web-process import path."""
    from app.graph.clients import build_embedder

    return build_embedder()
