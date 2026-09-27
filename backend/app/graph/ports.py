"""Typed ports (dependency-injection interfaces) for the graph layer.

The agent brain must not import concrete service classes — that coupling is what
made the layer un-testable in isolation and created the latent graph ↔ services
import edge. Instead the brain depends on these Protocols; the composition root
(:func:`app.graph.factories.build_deps`) constructs the concrete services and
injects them via :class:`~app.graph.types.GraphDeps`.

Ports are intentionally loose-typed (``Any`` for domain objects): they describe
*what the brain calls*, not the full service surface, so the concrete service can
evolve without dragging the contract along.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.conversation_messaging.application.ports import DeliveryResultPort
from app.project_knowledge.application.retrieval import ProjectKnowledgeQueryPort
from app.recruitment.application.ports import (
    LeadContextQueryPort,
    LeadGenderPort,
    PersonaBodyResolver,
    RecommendationQueryPort,
)
from app.shared.application.outbound import OutboundTelemetry


@dataclass(frozen=True)
class SendOutcome:
    """Provider-neutral value result for synthetic graph send outcomes.

    The proactive turn constructs synthetic outcomes for non-send paths (the agent
    decided not to send, safety blocked, generation threw). The optional delivery
    metadata also lets the reactive runner represent a missing durable command
    without constructing a provider service's concrete result type.
    """

    ok: bool
    msg_id: str | None = None
    error: str | None = None
    error_class: str | None = None
    suppressed: bool = False
    telemetry: OutboundTelemetry | None = None


class DirectMessageSenderPort(Protocol):
    """Direct provider-neutral sender used by graph execution and test adapters."""

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        quote_message_id: str | None = None,
    ) -> DeliveryResultPort: ...


# TypeSafe Jev decision model. The graph depends on this Protocol, never on the
# HTTP client (graph/decisions.py); tests inject stubs.
class TurnDecisionsPort(Protocol):
    """One parallel decision fan-out over a single inbound turn."""

    async def decide_turn(
        self,
        *,
        user_text: str,
        recent_messages: list[Any],
        profile_name: str = "",
        include_gender: bool = True,
    ) -> TurnDecisions: ...


@dataclass(frozen=True)
class TurnDecisions:
    """Raw, calibrated judgments for one inbound turn (see graph/decisions.py).

    ``router.route_from_decisions`` owns the policy that turns these raw
    judgments into a :class:`~app.graph.router.TurnRoute` (strategy, tools,
    trace reason). ``degraded=True`` marks the neutral fallback produced when
    Jev is unconfigured, unreachable, or returned an unusable answer.
    """

    intent: str = "general"
    intent_confidence: float = 0.1
    vacancy_listing: bool = False
    sort_by: str | None = None
    pleasantry: bool = False
    recent_vacancy: bool = False
    contact_info: bool = False
    # The assistant's previous reply was mid-way through an account/system
    # support flow (the TingTing reset steps). Lets a short follow-up — "sao
    # rồi", "ok", a bare phone number — stay on that flow and keep its tools
    # instead of being routed as small talk and stalling the employee.
    recent_account_support: bool = False
    # Candidate gender judged from the profile display name plus the candidate's
    # own messages: "male" | "female" | "unknown". Only a stored value changes how
    # the bot addresses the candidate (services/lead/normalizers.address_form).
    gender: str = "unknown"
    gender_confidence: float = 0.0
    # True when the candidate explicitly self-refers or states their gender in
    # the current message — that outranks an earlier inferred stored value.
    gender_stated: bool = False
    # True when Jev judged the provider display label (``profile_name``) a
    # plausible real human name. The runner persists it into a blank lead name.
    profile_name_is_name: bool = False
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    degraded: bool = False


@dataclass(frozen=True)
class FaqBypassResult:
    """A high-confidence FAQ answer ready to send without an LLM turn.

    The deterministic FAQ-bypass cascade returns this when it is confident;
    ``None`` means "abstain — route to the agent". ``answer`` is the only field
    the runner sends; the rest are carried for the decision log.

    ``runner_up_score`` carries the second-best match's similarity so the runner
    can abstain on low-margin hits (top only slightly better than runner-up →
    fall through to the LLM). ``None`` when only one candidate was returned.
    """

    answer: str
    faq_id: str | None = None
    tier: str = ""  # exact / hybrid
    score: float = 0.0
    reason: str = ""
    latency_ms: float = 0.0
    runner_up_score: float | None = None


class ConversationStatePort(Protocol):
    async def record_proactive_outcome(
        self, conv: Any, *, message: str, result: Any, lock_owner: Any = None
    ) -> Any: ...

    async def release_lock(self, conv: Any, lock_owner: Any = None) -> None: ...


class ConversationPort(Protocol):
    """Subset of the conversation service surface the brain depends on."""

    state: ConversationStatePort

    async def get(self, conversation_id: Any) -> Any: ...

    async def last_messages(self, conv: Any, *, limit: int) -> list[Any]: ...

    async def record_bot_pending(self, conv: Any) -> Any: ...

    async def record_bot_outcome(
        self,
        conv: Any,
        *,
        version_at_start: int,
        reply: str,
        started_at: Any,
        sent: bool,
        pending_message_id: int | None,
        external_error: str | None = None,
        zalo_message_id: str | None = None,
        stage_timings: dict | None = None,
        lock_owner: Any = None,
        delivery_status: Any = None,
        trace_id: str | None = None,
        outcome_metadata: dict | None = None,
        decision_trace: dict | None = None,
        outbox_channel: str | None = None,
        outbox_payload: dict | None = None,
    ) -> None: ...

    async def recheck_ownership(
        self, conv: Any, version_at_start: int, lock_owner: Any = None
    ) -> bool: ...

    async def claim_send(
        self,
        conv: Any,
        *,
        version_at_start: int,
        lock_owner: Any,
        pending_message_id: int | None,
        reply: str,
        outbox_channel: str | None = None,
        outbox_payload: dict | None = None,
    ) -> bool: ...

    async def dispatch_outbound_message(
        self, *, message_id: int
    ) -> DeliveryResultPort | None: ...

    async def acquire_lock(self, conv_id: Any) -> Any: ...


class LeadContextPort(LeadContextQueryPort, Protocol):
    """Lead-profile context the brain injects into the agent prompt.

    ``context`` does one DB fetch and returns both the profile text and the
    next lead-collection question (``""`` each on miss); ``profile_text`` is the
    single-fetch flavor used by the proactive turn. ``instruction`` is a pure
    prompt-assembly post-processor. The agent is the single owner of contact
    questions — there is no post-reply CTA append.
    """

    pass


class RuntimePolicyPort(Protocol):
    """Resolve only an active, validated installation into immutable turn policy."""

    async def resolve_active_policy(self) -> Any: ...

    async def runtime_stamp_is_current(
        self, *, revision_id: str, authority_generation: int, runtime_fingerprint: str
    ) -> bool: ...


class GraphRetrievalPort(
    ProjectKnowledgeQueryPort,
    PersonaBodyResolver,
    RecommendationQueryPort,
    Protocol,
):
    """Graph-owned query surface composed from bounded-context read ports."""

    async def match_memories(
        self, embedding: str, top_k: int, filters_json: str
    ) -> list[Any]: ...

    # Recruitment-domain reads the job-feature and income-comparison tools
    # need. The retrieval facade serves both through its recommendation seam;
    # they are declared here on the composite port because neither bounded-
    # context read port owns them (job features and income summaries are
    # recruitment agent surface, not project-knowledge queries).
    async def job_features_for_project(self, project_id: Any) -> list[Any]: ...
    async def income_summary_for_active_projects(self) -> list[Any]: ...

    # Deployment-wide TingTing password-reset integration (settings-managed).
    # Not project surface: the origin and key come from the integration settings
    # and one workflow serves every tenant, so the tool takes no project scope.
    async def tingting_api_configured(self) -> bool: ...
    async def call_tingting_api(
        self,
        *,
        method: str,
        path: str,
        params: dict | None,
    ) -> Any: ...
    # Server-side reset-flow state, keyed by the employee's phone digits. The
    # OTP session and the reset token must outlive the turn that produced them:
    # the agent's message list does not, so the model can never carry them.
    async def tingting_flow_state(self, phone: str) -> dict: ...
    async def save_tingting_flow_state(self, phone: str, state: dict) -> dict: ...
    async def clear_tingting_flow_state(self, phone: str) -> None: ...


class FaqBypassPort(Protocol):
    """Deterministic, non-LLM FAQ short-circuit that runs before the agent node.

    Returns a ready-to-send :class:`FaqBypassResult` on a high-confidence hit, or
    ``None`` to abstain (the agent then handles the turn as usual). Backed by
    :class:`app.graph.adapters._FaqBypassAdapter`; ``None`` in graph unit tests.
    """

    async def try_answer(self, user_text: str) -> FaqBypassResult | None: ...


class DirectContextPort(Protocol):
    async def resolve(self, conversation: Any, user_text: str) -> Any: ...


__all__ = [
    "SendOutcome",
    "DeliveryResultPort",
    "DirectMessageSenderPort",
    "FaqBypassResult",
    "FaqBypassPort",
    "ConversationPort",
    "ConversationStatePort",
    "LeadContextPort",
    "LeadGenderPort",
    "DirectContextPort",
    "GraphRetrievalPort",
]
