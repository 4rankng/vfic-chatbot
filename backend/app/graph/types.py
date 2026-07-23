"""Shared graph types: the BotRunState payload + the GraphDeps injection container."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import AsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NotRequired, TypedDict

from app.graph.llm import AgentModel, Embedder, SafetyModel
from app.graph.message_values import speaker_label
from app.graph.ports import (
    ConversationPort,
    DirectContextPort,
    FaqBypassPort,
    LeadContextPort,
    ReplyPolicyPort,
    GraphRetrievalPort,
    RuntimePolicyPort,
)
from app.recruitment.application.ports import ProactiveStatePort
from app.conversation_messaging.application.ports import DeliveryStatusValuesPort

# TYPE_CHECKING avoids pulling asyncpg into the runtime import path; the
# annotation is stringified by ``from __future__ import annotations`` anyway,
# but the explicit guard keeps linters/mypy happy without the import cost.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class BotRunState:
    conversation_id: str
    version_at_start: int
    user_text: str
    user_name: str = ""
    # OA CS replies must quote the inbound message they answer. Bot Platform
    # ignores this value; it is persisted with the inbound Message and carried
    # through direct, manual-release and recovery turns.
    reply_to_message_id: str = ""
    # Owner token acquired by the webhook/reconcile scheduler before enqueue.
    # Empty means legacy/no-owner jobs keep the previous version-only guard.
    lock_owner: str = ""
    attempt: int = 0
    reply: str = ""
    pending_message_id: int | None = None
    # Propagated ~10s turn deadline, in epoch seconds. The webhook stamps
    # ``received_at_epoch`` (time.time()) into the job so the budget survives the
    # FastAPI→RQ process boundary that time.monotonic() cannot cross; the worker
    # derives ``deadline_at_epoch = received_at_epoch + sla_seconds``. Stages check
    # ``_remaining(state)`` against it. ``0.0`` = unset → unbounded (legacy, tests).
    received_at_epoch: float = 0.0
    deadline_at_epoch: float = 0.0
    # Epoch (time.time()) stamped at RQ job entry by the worker, so run_turn can
    # split the enqueue→turn-start preamble (build_deps + Phase-0 scan) from the
    # webhook→pickup gap. 0.0 = unset (tests / pre-instrumentation).
    preamble_start_epoch: float = 0.0
    # webhook_high depth snapshot at job entry (None when Redis was unreachable).
    # Carried into stage_timings so the dashboard correlates latency with queue
    # saturation without re-implementing the dead chat_turn_start log.
    queue_depth: int | None = None
    # ``queued`` for normal RQ turns, ``recovery`` for offline reconciliation,
    # and ``direct`` for the retained ASGI adapter. Stored only in stage timings.
    execution_source: str = "recovery"
    # Webhook request_id propagated end-to-end so one trace_id query returns
    # every log line for a single candidate message's journey. Empty for legacy
    # jobs / tests; stamped on BotRun.trace_id by record_bot_outcome.
    trace_id: str = ""
    # Immutable authority captured when the inbound was accepted. Empty values
    # are legacy/test work and must not be treated as active authority.
    runtime_revision_id: str = ""
    authority_generation: int | None = None
    runtime_fingerprint: str = ""


class TurnOutcome(TypedDict):
    """Result of a reactive (``run_turn``) or proactive (``run_proactive_turn``) turn.

    ``outcome`` is always present (sent / suppressed / error / send_failed, with the
    proactive path prefixing ``proactive:``). ``reply`` and ``reason`` are optional
    depending on the branch taken.
    """

    outcome: str
    reply: NotRequired[str]
    reason: NotRequired[str]


@dataclass(frozen=True, slots=True)
class ResolvedToolRegistry:
    """Immutable, per-turn allowlist. Known but disabled tools are unreachable."""

    names: frozenset[str]

    def allows(self, name: str) -> bool:
        return name in self.names


@dataclass(frozen=True, slots=True)
class ResolvedRuntimePolicy:
    """Active installation policy after all database-backed checks have passed."""

    revision_id: str
    fingerprint_checksum: str
    pack_key: str
    capability_ids: frozenset[str]
    terminology: dict[str, str]
    persona_body: str
    tool_registry: ResolvedToolRegistry


@dataclass
class GraphDeps:
    db: AsyncSession  # injected at runtime; AsyncSession only for type-checking
    agent: AgentModel
    embedder: Embedder
    zalo: Any
    conversation: ConversationPort
    retrieval: GraphRetrievalPort
    reply_policy: ReplyPolicyPort
    # Unused after the LLM-judge removal; kept for GraphDeps API stability (tests
    # still inject safety=...). Sits with the other defaulted fields by dataclass rule.
    safety: SafetyModel | None = None
    # Lead-profile context for the agent prompt. None in tests that stub the turn.
    lead: LeadContextPort | None = None
    # Factory that yields a fresh GraphRetrievalPort on its own DB session, enabling
    # parallel tool dispatch (each concurrent tool call gets an isolated session).
    # None → tools run sequentially on the shared ``retrieval`` (tests, legacy).
    make_retrieval: Callable[[], AsyncContextManager[GraphRetrievalPort]] | None = None
    # Deterministic FAQ short-circuit (runs before the agent node). None in tests.
    faq_bypass: FaqBypassPort | None = None
    # Proactive follow-up guard: (allowed, reason). None in reactive-only tests.
    followup_allowed: Callable[[Any], Awaitable[tuple[bool, str]]] | None = None
    # Fire-and-forget candidate extraction after a SENT reply.
    # None in tests -> persistence is skipped.
    persist: Callable[[dict], None] | None = None
    # Best-effort OA display-name/avatar enrichment after ownership validation
    # and before lead context is assembled. None for non-OA/test deployments.
    enrich_oa_profile: Callable[[str, str], Awaitable[bool]] | None = None
    # New manifest-composed runtime authority. It is intentionally not attached
    # to the legacy delivery path until Phase 7 has the full dispatch fence.
    runtime_policy: RuntimePolicyPort | None = None
    # Resolves the active Agent's standalone KB without exposing retrieval/tools.
    direct_context: DirectContextPort | None = None
    # Recruitment-owned persistence and history seam for proactive turns.
    proactive_state: ProactiveStatePort | None = None
    # Persistence enum translation injected by the messaging composition root.
    delivery_statuses: DeliveryStatusValuesPort | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _speaker(msg) -> str:
    """Map ``Message.sender`` to a Vietnamese label.

    Shared by both ``runner.py`` (reactive turns) and ``proactive.py``
    (proactive nudges) to avoid drift between identical label maps.
    """
    return speaker_label(msg)
