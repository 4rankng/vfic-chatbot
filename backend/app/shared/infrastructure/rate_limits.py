"""API-facing rate-limit adapters (SEC-04).

``app/api/*`` may not import ``app.core`` (enforced by
``tests/test_architecture_boundaries.py``), so the limiter entry points the API
routers call live here and delegate to the Redis bucket primitives in
``app.core.ratelimit``: a bucket admits at most ``limit`` requests per
``window`` seconds and a rejected request never extends that window.
Limits, windows, and the fail-open choice come from settings
(``ratelimit_webhook_*`` / ``ratelimit_llm_*``) so an operator can tune
them without a deploy.

Bucket shape: one bucket per protected route. A burst on a cheap route
(``/leads/{id}/assist`` is a DB read) must not consume the budget of an expensive
one (``/web-chat-turn`` spends an LLM call), and the webhook bucket is keyed by
client IP because webhook callers are unauthenticated.
"""

from __future__ import annotations

import uuid

from fastapi import Request

from app.core.config import get_settings
from app.core.ratelimit import enforce_rate_limit, enforce_rate_limit_key

_WEBHOOK_PREFIX = "webhook"
_JOBS_SEARCH_PREFIX = "jobs-search"
_RAG_TEST_PREFIX = "knowledge-rag-test"
_WEB_CHAT_TURN_PREFIX = "web-chat-turn"
_LEAD_ASSIST_PREFIX = "lead-assist"
_LEAD_CHATOPS_ACTION_PREFIX = "lead-chatops-action"


async def enforce_webhook_rate_limit(request: Request) -> None:
    """Per-client-IP cap for the inbound webhook POSTs.

    Fail-open by contract: a Redis hiccup must never drop candidate messages
    (Zalo/Meta retry on non-2xx, so rejecting here would also amplify load).
    """
    settings = get_settings()
    await enforce_rate_limit(
        request,
        _WEBHOOK_PREFIX,
        limit=settings.ratelimit_webhook_limit,
        window=settings.ratelimit_webhook_window_seconds,
    )


async def _enforce_user_budget(prefix: str, user_id: uuid.UUID | str) -> None:
    settings = get_settings()
    await enforce_rate_limit_key(
        prefix,
        str(user_id),
        limit=settings.ratelimit_llm_limit,
        window=settings.ratelimit_llm_window_seconds,
        fail_open=not settings.ratelimit_llm_fail_closed,
    )


async def enforce_jobs_search_rate_limit(user_id: uuid.UUID | str) -> None:
    """Per-user cap for ``POST /jobs/search`` (one embedding call per request)."""
    await _enforce_user_budget(_JOBS_SEARCH_PREFIX, user_id)


async def enforce_rag_test_rate_limit(user_id: uuid.UUID | str) -> None:
    """Per-user cap for ``POST /knowledge/projects/{id}/rag/test``."""
    await _enforce_user_budget(_RAG_TEST_PREFIX, user_id)


async def enforce_web_chat_turn_rate_limit(user_id: uuid.UUID | str) -> None:
    """Per-user cap for ``POST /conversations/{id}/web-chat-turn`` (a full bot turn)."""
    await _enforce_user_budget(_WEB_CHAT_TURN_PREFIX, user_id)


async def enforce_lead_assist_rate_limit(user_id: uuid.UUID | str) -> None:
    """Per-user cap for ``GET /leads/{id}/assist``."""
    await _enforce_user_budget(_LEAD_ASSIST_PREFIX, user_id)


async def enforce_lead_chatops_action_rate_limit(user_id: uuid.UUID | str) -> None:
    """Per-user cap for ``POST /leads/{id}/chatops-actions/{action}``."""
    await _enforce_user_budget(_LEAD_CHATOPS_ACTION_PREFIX, user_id)


__all__ = [
    "enforce_jobs_search_rate_limit",
    "enforce_lead_assist_rate_limit",
    "enforce_lead_chatops_action_rate_limit",
    "enforce_rag_test_rate_limit",
    "enforce_web_chat_turn_rate_limit",
    "enforce_webhook_rate_limit",
]
