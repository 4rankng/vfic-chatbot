"""Provider chat-model constructors and role/provider resolution.

Split out of ``clients.py`` so the OpenAI-compatible client builders
(MiniMax / OpenRouter / operator-supplied custom endpoint) sit beside the
reasoning-mode and output-cap policy they apply, instead of in the module that
carries the generation loop. ``langchain-openai`` / ``langchain-core`` stay
imported lazily inside the builders so importing this module is cheap and free
of optional-dependency failures at import time.

``clients.py`` re-exports these names, so ``from app.graph.clients import
_chat_for_role`` keeps working; ``factories.py`` binds its own imports of them
and is what monkeypatching targets (e.g. ``app.graph.factories._openrouter_chat``)
must point at.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import SecretStr

from app.core.config import get_settings
from app.graph.reasoning_compat import _reasoning_chat_class

ModelRole = Literal["agent", "extractor", "digest"]
# The three configurable providers. "custom" is any OpenAI-compatible endpoint
# the operator supplies (base URL + model ids), e.g. Xiaomi MiMo.
LlmProvider = Literal["minimax", "openrouter", "custom"]

_REASONING_MODES = ("off", "low", "default")
_PROVIDER_ORDER: tuple[LlmProvider, ...] = ("minimax", "openrouter", "custom")


class _AgentLimits(TypedDict, total=False):
    """Output cap applied to agent-role calls only; empty for other roles.

    These splat into this module's own builders, so the single key is worth
    declaring: checked key-by-key it matches their ``max_tokens`` parameter,
    while an undeclared dict was read as an argument for every parameter.
    """

    max_tokens: int | None


def _resolve_reasoning_mode(explicit: str | None = None) -> str:
    """Resolve the reasoning mode: explicit arg, then settings, else ``off``.

    Default is ``off`` — the chain-of-thought is never shown to the candidate and
    only inflates wall time (measured: disabling it on the MiMo token plan cut a
    12k-token turn from 6,925 ms to 5,227 ms at equal answer length). Read via
    ``getattr`` so the behaviour is live before the settings field is added, and a
    deployment that wants the old behaviour can set ``LLM_REASONING_MODE=default``.
    """
    if explicit:
        mode = explicit.strip().lower()
    else:
        mode = str(getattr(get_settings(), "llm_reasoning_mode", "off") or "off").strip().lower()
    return mode if mode in _REASONING_MODES else "off"


def _agent_max_tokens() -> int | None:
    """Output cap for the agent lane, or ``None`` when unset.

    Measured on the token plans: a 400-token cap still ended with
    ``finish_reason=stop`` (no truncation) and cut a MiniMax turn from 8,489 ms to
    ~6,100 ms; 250 truncated mid-answer on MiniMax. Unset keeps today's unbounded
    behaviour, so this only takes effect when an operator configures it.

    Nothing is configured by default: the admin knob's default is 0 ("no cap"), so
    the answer lane runs unbounded unless an operator chooses the wall-time lever.

    On MiniMax M2.x a configured cap covers the inline `` thinking`` deliberation as
    well as the answer (the provider cannot disable thinking, and the deliberation
    is returned inside ``content``), so a value sized for the answer alone cuts the
    answer mid-word. Such a turn is completed by the answer-completion guard in
    ``answer_repair`` instead of shipping the cut — at the cost of one extra
    model call, which is the second reason the shipped default is no cap.
    """
    raw = getattr(get_settings(), "llm_agent_max_tokens", 0) or 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _minimax_chat(
    model: str,
    *,
    temperature: float,
    max_retries: int = 0,
    api_key: str | None = None,
    max_tokens: int | None = None,
):
    """OpenAI-compatible MiniMax client from settings. Shared construction so
    model / base_url / timeout cannot drift between build_deps and the extractor.

    ``max_retries`` defaults to 0: the agent loop handles 429 explicitly via
    ``_llm_call_with_retry`` (one backoff retry, then LLMThrottled → static
    degradation reply). The openai library's built-in retry would just waste
    time (3× the timeout) on top of that, so it stays off.

    Reasoning cannot be switched off on this endpoint (measured 2026-09-26 on
    ``api.minimax.io/v1`` with MiniMax-M2.7-highspeed): ``thinking:{type:disabled}``,
    ``enable_thinking:false``, ``reasoning:{enabled:false}``, ``reasoning_effort:none``
    and ``chat_template_kwargs`` all still returned 120–220 reasoning tokens, and
    decode stayed ~40–60 tok/s. So this builder deliberately sends no reasoning
    field — an unsupported field would risk 4xx on the primary lane for no gain.
    ``max_tokens`` is the only lever that bounds a MiniMax turn.
    """
    s = get_settings()
    resolved_api_key = api_key or s.minimax_api_key
    if not resolved_api_key:
        raise RuntimeError("MINIMAX_API_KEY is required for MiniMax chat")
    chat_class = _reasoning_chat_class()
    kwargs: dict = {}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return chat_class(
        model=model,
        api_key=SecretStr(resolved_api_key),
        base_url=s.minimax_base_url,
        timeout=s.minimax_request_timeout,
        temperature=temperature,
        max_retries=max_retries,
        trace_provider="minimax",
        # Streaming must still report token usage (progressive delivery path).
        stream_usage=True,
        **kwargs,
    )


# Vendors known to accept an explicit thinking-disable field on their
# OpenAI-compatible endpoint. Everything else (an operator-supplied custom
# vendor) gets no reasoning field at all: an unknown vendor can reject an
# undocumented request field and would 4xx the whole lane, so the change stays
# opt-in per known host instead of global.
_THINKING_DISABLE_HOSTS = ("xiaomimimo",)


def _custom_supports_thinking_disable(base_url: str) -> bool:
    host = (base_url or "").split("//", 1)[-1].split("/", 1)[0].lower()
    return any(marker in host for marker in _THINKING_DISABLE_HOSTS)


def _custom_chat(
    model: str,
    *,
    temperature: float,
    api_key: str,
    base_url: str,
    timeout: int | None = None,
    max_retries: int = 0,
    reasoning_mode: str | None = None,
    max_tokens: int | None = None,
):
    """OpenAI-compatible client for the admin-configured failover provider.

    Everything (endpoint, model id, credential) comes from the settings page
    rather than from code, so pointing this at a different vendor is an operator
    action. ``max_retries=0`` for the same reason as the other builders: the
    agent loop owns retry/failover policy.

    Reasoning: the Xiaomi MiMo token plan honours ``thinking:{type:disabled}``
    (measured 2026-09-26: reasoning tokens 41 → 0, and one 12k-token turn dropped
    6,925 ms → 5,227 ms at equal answer length). MiMo exposes no graded budget, so
    ``low`` is honoured as ``disabled``. Only hosts in
    ``_THINKING_DISABLE_HOSTS`` receive the field; any other custom vendor is
    left untouched.
    """
    if not api_key:
        raise RuntimeError("failover provider API key is required")
    if not base_url:
        raise RuntimeError("failover provider base URL is required")
    if not model:
        raise RuntimeError("failover provider model is required")
    s = get_settings()
    chat_class = _reasoning_chat_class()
    mode = _resolve_reasoning_mode(reasoning_mode)
    kwargs: dict = {}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if mode in {"off", "low"} and _custom_supports_thinking_disable(base_url):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return chat_class(
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
        timeout=timeout or s.custom_llm_request_timeout,
        temperature=temperature,
        max_retries=max_retries,
        trace_provider="fallback",
        stream_usage=True,
        **kwargs,
    )


def _openrouter_chat(
    model: str,
    *,
    temperature: float,
    timeout: int | None = None,
    json_mode: bool = False,
    max_retries: int = 0,
    api_key: str | None = None,
    reasoning_mode: str | None = None,
    max_tokens: int | None = None,
):
    """OpenAI-compatible OpenRouter client from settings.

    ``reasoning_mode`` (``off`` | ``low`` | ``default``) maps to OpenRouter's
    documented ``reasoning`` body field. The previous behaviour pinned
    ``effort: high`` on every agent call purely to capture the chain-of-thought
    into the decision trace — the user never sees it, and it multiplied wall time
    on the deepest-reasoning models, so it is no longer forced.
    """
    s = get_settings()
    resolved_api_key = api_key or s.openrouter_api_key
    if not resolved_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for OpenRouter chat")
    kwargs: dict[str, Any] = (
        {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
    )
    mode = _resolve_reasoning_mode(reasoning_mode)
    if mode == "off":
        kwargs["extra_body"] = {"reasoning": {"enabled": False}}
    elif mode == "low":
        kwargs["extra_body"] = {"reasoning": {"effort": "low", "exclude": False}}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    chat_class = _reasoning_chat_class()
    return chat_class(
        model=model,
        api_key=SecretStr(resolved_api_key),
        base_url=s.openrouter_base_url,
        timeout=timeout or s.openrouter_request_timeout,
        temperature=temperature,
        max_retries=max_retries,
        trace_provider="openrouter",
        stream_usage=True,
        # Stable system block as an explicit cache prefix (transport metadata
        # only — the prompt text is unchanged). OpenRouter's docs accept the
        # Anthropic-style breakpoint on a content block and translate it to
        # the routed provider's own syntax; automatic-caching providers
        # upstream simply don't need it.
        system_prefix_cache_control={"type": "ephemeral"},
        **kwargs,
    )


def _active_llm_provider(
    settings=None,
    *,
    minimax_enabled: bool | None = None,
    openrouter_enabled: bool | None = None,
    custom_enabled: bool | None = None,
    default_provider: LlmProvider | None = None,
) -> LlmProvider:
    """Return the provider that serves the first attempt of each turn.

    Resolution order: the operator's chosen default when that provider is
    enabled, then any other enabled provider. Quota failover is handled per-call
    in ``_llm_call_with_retry``; this only picks where a turn starts.
    """
    s = settings or get_settings()
    mm_on = getattr(s, "minimax_enable", True) if minimax_enabled is None else minimax_enabled
    or_on = (
        getattr(s, "openrouter_enable", False) if openrouter_enabled is None else openrouter_enabled
    )
    custom_on = (
        getattr(s, "custom_llm_enable", False) if custom_enabled is None else custom_enabled
    )
    enabled: dict[LlmProvider, bool] = {
        "minimax": mm_on,
        "openrouter": or_on,
        "custom": custom_on,
    }
    preferred = default_provider or getattr(s, "llm_default_provider", "minimax")
    # Return the literal from the loop rather than the configured string: they
    # are equal whenever the configured value names a real provider, and a
    # value that names none still falls through to the enabled-provider scan,
    # exactly as the previous ``enabled.get`` lookup did.
    for name in _PROVIDER_ORDER:
        if name == preferred and enabled[name]:
            return name
    for name in _PROVIDER_ORDER:
        if enabled[name]:
            return name
    raise RuntimeError(
        "No LLM provider enabled: enable MiniMax, OpenRouter, or the custom provider"
    )


def _chat_for_role(
    role: ModelRole,
    *,
    temperature: float,
    json_mode: bool = False,
    minimax_api_key: str | None = None,
    openrouter_api_key: str | None = None,
    minimax_enabled: bool | None = None,
    openrouter_enabled: bool | None = None,
    custom_enabled: bool | None = None,
    custom_config=None,
    default_provider: LlmProvider | None = None,
    openrouter_agent_model: str | None = None,
    openrouter_extractor_model: str | None = None,
    openrouter_digest_model: str | None = None,
    reasoning_mode: str | None = None,
    max_tokens: int | None = None,
):
    """Build the OpenAI-compatible chat client for an agent/extractor/digest role.

    Returns a plain ``ChatOpenAI`` for the single configured provider. The
    active provider is resolved once by ``_active_llm_provider`` (default first,
    falling back to whichever is enabled). Cross-provider failover is NOT wired
    here: the agent loop owns it per-call via ``_llm_call_with_retry`` with a
    failover chain from ``factories._build_failover_chain``, which keeps these
    clients stateless and safe to cache across turns.

    ``reasoning_mode`` / ``max_tokens`` are the admin-configured latency knobs
    resolved by ``build_cached_clients``. An explicit value wins; otherwise the
    settings-backed default applies (``_resolve_reasoning_mode`` /
    ``_agent_max_tokens``). ``max_tokens=0`` means "no cap".
    """
    s = get_settings()
    provider = _active_llm_provider(
        s,
        minimax_enabled=minimax_enabled,
        openrouter_enabled=openrouter_enabled,
        custom_enabled=custom_enabled,
        default_provider=default_provider,
    )
    # The output cap and reasoning mode apply to the answer lane only: the
    # extractor/digest roles produce bounded structured payloads already, and
    # capping them would risk truncating JSON. An explicit caller value (the
    # admin-managed settings resolved by build_cached_clients) wins over the
    # settings-backed default.
    if role == "agent":
        resolved_cap = max_tokens if max_tokens is not None else _agent_max_tokens()
        agent_limits: _AgentLimits = {"max_tokens": resolved_cap}
        agent_reasoning = reasoning_mode or _resolve_reasoning_mode()
    else:
        agent_limits = {}
        agent_reasoning = "default"

    if provider == "custom":
        if custom_config is None or not custom_config.usable:
            raise RuntimeError("custom LLM provider selected but not fully configured")
        model = custom_config.agent_model
        return _custom_chat(
            model,
            temperature=temperature,
            api_key=custom_config.api_key,
            base_url=custom_config.base_url,
            reasoning_mode=agent_reasoning,
            **agent_limits,
        )

    if provider == "openrouter":
        resolved_openrouter_key = openrouter_api_key or s.openrouter_api_key
        model = {
            "agent": openrouter_agent_model or s.openrouter_agent_model,
            "extractor": openrouter_extractor_model or s.openrouter_extractor_model,
            "digest": (
                openrouter_digest_model
                or s.openrouter_digest_model
                or openrouter_agent_model
                or s.openrouter_agent_model
            ),
        }[role]
        timeout = s.openrouter_digest_timeout if role == "digest" else s.openrouter_request_timeout
        return _openrouter_chat(
            model,
            temperature=temperature,
            timeout=timeout,
            json_mode=json_mode,
            api_key=resolved_openrouter_key,
            reasoning_mode=agent_reasoning,
            **agent_limits,
        )

    # minimax
    resolved_minimax_key = minimax_api_key or s.minimax_api_key
    if role == "digest":
        if not resolved_minimax_key:
            raise RuntimeError("MINIMAX_API_KEY is required for MiniMax JSON generation")
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = (
        {"model_kwargs": {"response_format": {"type": "json_object"}}} if json_mode else {}
    )
        return ChatOpenAI(
            model=s.minimax_digest_model or s.minimax_agent_model,
            api_key=SecretStr(resolved_minimax_key),
            base_url=s.minimax_base_url,
            timeout=s.minimax_digest_timeout,
            temperature=temperature,
            **kwargs,
        )
    model = s.minimax_agent_model if role == "agent" else s.minimax_extractor_model
    return _minimax_chat(
        model,
        temperature=temperature,
        api_key=resolved_minimax_key,
        **agent_limits,
    )
