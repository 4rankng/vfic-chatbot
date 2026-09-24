"""Cross-group helpers: secret-status projection, value coercion, failover ranking.

Shared by every provider group in the package (Zalo, the LLM chain, Facebook) so
no group's module needs to import another's.
"""

from __future__ import annotations

from typing import Iterable

LLM_DEFAULT_PROVIDER = "llm_default_provider"
# Operator-ranked spare order, stored as CSV ("openrouter,custom"). The default
# provider always starts a turn; this ranks whoever takes over on quota death.
LLM_FAILOVER_ORDER = "llm_failover_order"


def _secret_status(value: str) -> dict:
    """Status-only projection for an authorizing secret (SEC-07).

    Admin GETs used to answer with ``first4...last4`` for every credential,
    which leaked eight characters of each and narrowed brute force on the Meta
    app secret — the HMAC key that authenticates every Messenger webhook. An
    authorizing secret now reports only whether it is configured and how long it
    is; no character derived from the value leaves the process.

    The field name stays ``preview`` because the admin UI renders it as the
    field placeholder (``SecretStatus.preview``); only the content changed from
    a character preview to a status string.
    """
    value = (value or "").strip()
    if not value:
        return {"configured": False, "preview": None}
    return {"configured": True, "preview": f"{len(value)} ký tự"}


def _bool_value(value: str | None, fallback: bool) -> bool:
    if value is None:
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}


# The selectable providers. "custom" is the operator-supplied OpenAI-compatible
# endpoint; an unrecognised stored value falls back to minimax rather than
# leaving the process with no provider.
_SELECTABLE_PROVIDERS = frozenset({"minimax", "openrouter", "custom"})
_CANONICAL_PROVIDER_ORDER = ("minimax", "openrouter", "custom")


def _provider_value(value: str | None, fallback: str) -> str:
    candidate = (value or fallback or "minimax").strip().lower()
    return candidate if candidate in _SELECTABLE_PROVIDERS else "minimax"


def normalize_llm_failover_order(
    raw: str | Iterable[str] | None,
) -> tuple[str, ...]:
    """Parse the operator-ranked order into a full, canonical-complete ranking.

    Unknown or stale names are dropped and duplicates collapse to their first
    occurrence; providers the operator left unranked trail in canonical order,
    so the result is always a complete permutation the chain builder can rank
    by without special cases.
    """
    parts: list[str] = (
        [part.strip() for part in raw.split(",")] if isinstance(raw, str) else list(raw or [])
    )
    ranked = [part for part in dict.fromkeys(parts) if part in _SELECTABLE_PROVIDERS]
    return tuple(ranked + [name for name in _CANONICAL_PROVIDER_ORDER if name not in ranked])
