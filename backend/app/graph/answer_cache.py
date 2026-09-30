"""Answer cache: serve the previously sent reply for a repeated KB question.

The evidence cache (``search_knowledge``) saves the retrieval round; this saves
the *whole agent loop*, including the model call that authors the prose. A hit is
one Redis read plus (paraphrase tier only) one cached embedding.

Two tiers, both keyed by a ``scope`` token that folds the project scope, the
address bucket and the ``knowledge``/``preamble``/``jobs`` version counters:

  * **exact** (``answer_cache_enabled``, default ON) — same normalized question
    (``normalize_query``: NFC + lowercase + collapsed whitespace), same scope.
    Needs no embedding.
  * **semantic** (``answer_cache_semantic_enabled``, default OFF) — a paraphrase
    above ``answer_cache_threshold`` within the same scope, reusing
    :mod:`app.graph.semantic_cache` (and therefore its version-based
    invalidation).

**Eligibility is the load-bearing guard.** A reply is stored only for a turn
whose tools serve stateless Project information (see :data:`_PROJECT_DATA_TOOLS`)
— no memory read, no profile-ranked recommendation, no TingTing flow — and only
when the KB lookup returned usable evidence. A profile-collection ask is
explicitly *not* a disqualifier: the ask is generic and refusing it would mean
never caching anything for a new candidate, which is the dominant production
case (verified against the live model). On top of that,
:func:`is_shareable_reply` refuses to store a reply that names the lead.

Nothing here needs a write-path hook: every mutation of answerable project content
already bumps at least one of the three version counters this module reads, so
stale entries become unreachable the moment the data changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from hashlib import sha256

from app.core.cache import cache_get_json, cache_set_json, cache_version
from app.core.config import get_settings
from app.core.preamble_cache import NS_PREAMBLE
from app.graph.cache_key import normalize_query
from app.graph.embed_cache import cached_embed
from app.graph.llm import Embedder
from app.graph.semantic_cache import scope_key, semantic_cache_get, semantic_cache_put
from app.shared.domain.text import normalize_vietnamese_text

logger = logging.getLogger(__name__)

# The exact tier's Redis key. ``scope`` already carries the version counters, so
# no separate version namespace is needed here.
_EXACT_KEY = "answer:{scope}:{query_hash}"

# Continuation/anaphora markers (ASCII form of ``normalize_vietnamese_text``).
# A question carrying one of these cannot be answered from the question alone —
# it needs the preceding turn — so it is never cached. A false "not standalone"
# costs a cache miss, never a wrong answer; the list is therefore deliberately
# broad rather than minimal.
_ANAPHORA_MARKERS: tuple[str, ...] = (
    "con gi",
    "con gi nua",
    "the nao",
    "nhu the nao",
    "the a",
    "vay a",
    "sao a",
    "du an do",
    "ben do",
    "cho do",
    "cai do",
    "o do",
    "no la gi",
    "con khong",
    "nua khong",
    "them khong",
    "the con",
    "roi sao",
)

_MIN_QUESTION_CHARS = 8

# Mirrors ``graph.prefetch._usable_retrieval_prefetch``: these are the strings a
# tool returns when it produced no usable evidence, and a reply built on them
# must never be served as if it were an answer.
_NO_EVIDENCE_PREFIXES = ("Không tìm thấy", "Lỗi khi gọi tool", "unknown tool")

# Below this length a lead identifier is too generic to be evidence of
# personalization ("An", "09") — matching it would reject almost every reply.
_MIN_LEAD_IDENTIFIER_CHARS = 3

_LEAD_IDENTIFIER_FIELDS = ("name", "phone", "email")

# Tools whose reply is a function of the question and the Project data alone, so
# it is the same for every candidate and a repeated question can reuse it.
#
# Deliberately absent, and the reason the allowlist (not a deny list) is the
# guard: ``search_user_memory`` (remembered facts about this candidate), the
# profile-ranked recommendation tools, and the TingTing account flows. A new
# tool is therefore refused until someone classifies it here.
#
# ``list_active_jobs`` was the vacancy catalog before the 2026-10 rename to
# ``list_active_projects``; both spellings are accepted while the rename lands.
_PROJECT_DATA_TOOLS = frozenset(
    {
        "search_knowledge",
        "get_product_features",
        "search_bus_timetable",
        "compare_income",
        "list_active_projects",
        "list_active_jobs",
    }
)

# The subset whose arguments the model composes from the conversation rather than
# from the current question (filters, location, sort order). Cached only on a
# turn with no earlier messages, so a preference stated several turns ago cannot
# be folded into a reply that is then served to another candidate.
_CONTEXT_COMPOSED_TOOLS = frozenset({"list_active_projects", "list_active_jobs"})


@dataclass(frozen=True)
class AnswerCacheHit:
    """One cached answer. ``similarity`` is 1.0 on the exact tier."""

    result: str
    similarity: float
    tier: str


def is_standalone_kb_question(user_text: str) -> bool:
    """Whether ``user_text`` is self-contained enough to cache its answer.

    Rejects short fragments and any continuation/anaphora marker: those carry
    meaning only relative to the previous turn, so the same text can legitimately
    answer differently next time.
    """
    normalized = normalize_vietnamese_text(user_text or "")
    if len(normalized) < _MIN_QUESTION_CHARS:
        return False
    return not any(marker in normalized for marker in _ANAPHORA_MARKERS)


def is_answer_cacheable(
    *,
    allowed_tools: tuple[str, ...] | None = None,
    tingting_reset_allowed: bool,
    tingting_support_account: bool,
    has_conversation_history: bool,
    user_text: str,
) -> bool:
    """Whether this turn's reply may be reused for a later identical question.

    The tool allowlist is the load-bearing guard, and it encodes one rule: cache
    a reply only when it is **stateless Project information** — the same answer
    for every candidate. Everything the bot serves about a Project (its KB, its
    feature catalog, the active-project/vacancy catalog, the shuttle timetable,
    cross-project income) qualifies. A reply built with a candidate-dependent
    tool (``search_user_memory``, a profile-ranked recommendation) or a TingTing
    account flow never does, and neither does a low-confidence route
    (``allowed_tools is None``) that could call any tool at all.

    ``has_conversation_history`` narrows the catalog tools whose arguments the
    model composes itself (filters, location, sort order): with earlier messages
    in view it can fold in a preference stated several turns ago, which would
    make the reply candidate-specific even though the question reads standalone.
    The knowledge tools take their query from the current turn, so they are
    unaffected.

    A profile-collection ask is deliberately NOT a disqualifier: the ask is a
    generic instruction ("cho em xin tên để tiện hỗ trợ nhé"), identical for
    every candidate, and refusing it would mean never caching anything for a new
    candidate — the dominant production case (verified against the live model).
    Candidate-specific *content* is caught by :func:`is_shareable_reply`.
    """
    if tingting_reset_allowed or tingting_support_account:
        return False
    tools = tuple(allowed_tools or ())
    if not tools:
        return False
    if any(name not in _PROJECT_DATA_TOOLS for name in tools):
        return False
    if has_conversation_history and any(name in _CONTEXT_COMPOSED_TOOLS for name in tools):
        return False
    return is_standalone_kb_question(user_text)


def is_shareable_reply(reply: str, *, lead_row: dict | None) -> bool:
    """Whether ``reply`` is safe to hand to a different candidate later.

    Best-effort guard: the load-bearing guards are the project scope and
    :func:`is_answer_cacheable`. This one only refuses to store a reply that
    clearly cannot be reused — an empty reply, a no-evidence reply, or one that
    names the lead whose turn produced it.
    """
    text = (reply or "").strip()
    if not text:
        return False
    if text.startswith(_NO_EVIDENCE_PREFIXES):
        return False
    if not lead_row:
        return True
    normalized_reply = normalize_vietnamese_text(text)
    for field in _LEAD_IDENTIFIER_FIELDS:
        raw = lead_row.get(field)
        if raw is None:
            continue
        identifier = normalize_vietnamese_text(str(raw)).strip()
        if len(identifier) >= _MIN_LEAD_IDENTIFIER_CHARS and identifier in normalized_reply:
            return False
    return True


async def answer_project_scope(retrieval, project_slug: str | None) -> str:
    """The scope token for the project data this turn's answer was built from.

    Mirrors ``search_knowledge``'s scope resolution exactly: a slug names one
    project, otherwise the port's active-project list (the deployment-wide
    catalog). ``""`` means "not cacheable" — an unknown slug, a port with no
    reader, an empty list, or a failing read all fail closed rather than serving
    one Page's answer to another.
    """
    try:
        project_ids: list[str] | None = None
        if project_slug:
            pid = await retrieval.project_id_by_slug(project_slug, active_only=True)
            if pid is None:
                return ""
            project_ids = [str(pid)]
        else:
            active_project_ids = getattr(retrieval, "active_project_ids", None)
            if active_project_ids is None:
                return ""
            project_ids = await active_project_ids()
        if not project_ids:
            return ""
        return scope_key(sorted(str(pid) for pid in project_ids), None)
    except Exception:  # noqa: BLE001 — an unreadable scope is simply not cacheable
        logger.debug("answer cache scope resolution failed (non-fatal)", exc_info=True)
        return ""


async def answer_scope(
    *,
    project_scope: str,
    address: str,
    tenant_id: str = "default",
    language: str = "vi",
) -> str:
    """The 32-hex scope token every answer-cache entry is keyed by.

    Folds everything that determines the answer apart from the question itself:
    the tenant, the reply language, the three version counters every KB/chunk,
    category/project-metadata and job-derived write already bumps, the project
    scope, and the address bucket (``anh``/``chị``) the prompt was written with.
    A reply written with "anh" is therefore never served in the "chị" bucket.
    """
    parts = [
        "answer",
        tenant_id,
        language,
        await cache_version("knowledge"),
        await cache_version(NS_PREAMBLE),
        await cache_version("jobs"),
        project_scope,
        address,
    ]
    return sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


def _query_hash(query: str) -> str:
    return sha256(normalize_query(query).encode("utf-8")).hexdigest()[:32]


async def answer_cache_get(query: str, *, embedder: Embedder, scope: str) -> AnswerCacheHit | None:
    """Return the cached answer for ``query`` under ``scope``, or ``None``.

    The exact tier is tried first (no embedding). Every failure — disabled,
    empty scope, Redis error — is a miss.
    """
    s = get_settings()
    if not s.answer_cache_enabled or not scope:
        return None
    cached = await cache_get_json(_EXACT_KEY.format(scope=scope, query_hash=_query_hash(query)))
    if isinstance(cached, str) and cached:
        return AnswerCacheHit(result=cached, similarity=1.0, tier="exact")
    if not s.answer_cache_semantic_enabled:
        return None
    vector = await cached_embed(embedder, query)
    hit = await semantic_cache_get(
        vector,
        scope=scope,
        threshold=s.answer_cache_threshold,
        enabled=True,
    )
    if hit is None:
        return None
    return AnswerCacheHit(result=hit.result, similarity=hit.similarity, tier="semantic")


async def answer_cache_put(query: str, reply: str, *, embedder: Embedder, scope: str) -> None:
    """Store ``reply`` as the answer to ``query`` under ``scope``. Best-effort.

    The exact tier is always written; the paraphrase tier only when
    ``answer_cache_semantic_enabled``, so enabling the exact tier never pays for
    an embedding.
    """
    s = get_settings()
    if not s.answer_cache_enabled or not scope:
        return
    await cache_set_json(
        _EXACT_KEY.format(scope=scope, query_hash=_query_hash(query)),
        reply,
        s.answer_cache_ttl_seconds,
    )
    if not s.answer_cache_semantic_enabled:
        return
    vector = await cached_embed(embedder, query)
    await semantic_cache_put(
        vector,
        reply,
        scope=scope,
        enabled=True,
        capacity=s.answer_cache_capacity,
        ttl_seconds=s.answer_cache_ttl_seconds,
    )
