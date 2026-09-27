"""Routed pre-lookup heuristics for the agent loop.

The agent decides before the first model call whether a routed lookup can answer
the turn outright (contact/admin questions, focused-RAG, timetable, income
comparison, FAQ detail). This module owns the trigger heuristics, the argument
scoping, and the shared timing/fail-open wrapper; the tool loop that consumes
the results stays in ``graph/clients.py``.

The dispatcher is injected by the caller rather than imported here: the agent
loop owns the tool-dispatch binding, and a single binding must serve every
lookup in a turn.
"""

from __future__ import annotations

import logging
import time
import unicodedata

logger = logging.getLogger(__name__)


def _normalize_query_hint(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return ascii_text.replace("đ", "d").replace("Đ", "D").lower()


def _should_prefetch_knowledge(user_text: str) -> bool:
    """Detect queries where skipping KB retrieval causes false "I don't know" replies.

    Contact/admin/phone questions should see KB facts before the model answers.
    """
    text = _normalize_query_hint(user_text)
    contact_terms = (
        "lien he",
        "admin",
        "so dien thoai",
        "sdt",
        "phone",
        "hotline",
        "zalo",
        "den cong ty",
    )
    return any(term in text for term in contact_terms)


def _usable_retrieval_prefetch(result: object) -> bool:
    """Whether a routed retrieval result is authoritative enough to inject."""
    text = str(result or "").strip()
    if not text:
        return False
    return not text.startswith(("Không tìm thấy", "Lỗi khi gọi tool", "unknown tool"))


def _scope_project_tool_args(name: str, args: dict, project_slug: str | None) -> dict:
    """Force project-aware tools to the conversation's focused Project."""
    scoped = dict(args)
    if not project_slug:
        return scoped
    if name in {
        "search_knowledge",
        "list_active_jobs",
        "get_product_features",
    }:
        scoped["project_slug"] = project_slug
    return scoped


async def _prefetch_tool(
    retrieval,
    embedder,
    name: str,
    args: dict,
    metrics: dict | None,
    resolved_registry: frozenset[str] | None = None,
    *,
    dispatch,
) -> tuple[object, bool]:
    """Run one routed lookup with shared timing and fail-open semantics."""
    started = time.monotonic()
    if metrics is not None:
        metrics["prefetch_calls"] = metrics.get("prefetch_calls", 0) + 1
    try:
        result = await dispatch(
            retrieval,
            embedder,
            name,
            args,
            metrics=metrics,
            resolved_registry=resolved_registry,
        )
    except Exception:  # noqa: BLE001 — caller retains the normal tool loop
        logger.warning("%s prefetch failed", name, exc_info=True)
        result = ""
    finally:
        if metrics is not None:
            metrics["prefetch_ms"] = metrics.get("prefetch_ms", 0) + int(
                (time.monotonic() - started) * 1000
            )
    hit = _usable_retrieval_prefetch(result)
    if metrics is not None:
        metrics["prefetch_hit"] = hit
    return result, hit
