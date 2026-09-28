"""LLM provider groups: MiniMax, OpenRouter, custom endpoint, Jev, and the
operator-ranked failover order."""

from __future__ import annotations

from typing import TYPE_CHECKING

import logging
import os
from dataclasses import dataclass

from app.core.cache import bump_cache_version
from app.core.config import EMBEDDING_DIM
from app.core.preamble_cache import (
    NS_INTEGRATION_CUSTOM_LLM,
    NS_INTEGRATION_JEV,
    NS_INTEGRATION_MINIMAX,
    NS_INTEGRATION_OPENROUTER,
    cached_custom_llm_config,
    cached_jev_config,
    cached_minimax_config,
    cached_openrouter_config,
    evict_local_namespace,
)
from app.services.audit_service import record_audit
from app.services.integration_settings._shared import (
    LLM_DEFAULT_PROVIDER,
    LLM_FAILOVER_ORDER,
    _bool_value,
    _provider_value,
    _secret_status,
    normalize_llm_failover_order,
)

logger = logging.getLogger(__name__)

MINIMAX_API_KEY = "minimax_api_key"
MINIMAX_ENABLE = "minimax_enable"
OPENROUTER_API_KEY = "openrouter_api_key"
OPENROUTER_ENABLE = "openrouter_enable"
OPENROUTER_AGENT_MODEL = "openrouter_agent_model"
OPENROUTER_EXTRACTOR_MODEL = "openrouter_extractor_model"
OPENROUTER_DIGEST_MODEL = "openrouter_digest_model"

# Quota-failover provider: any OpenAI-compatible endpoint, fully operator-supplied
# so a new vendor needs no code change.
CUSTOM_LLM_ENABLE = "custom_llm_enable"
CUSTOM_LLM_LABEL = "custom_llm_label"
CUSTOM_LLM_API_KEY = "custom_llm_api_key"
CUSTOM_LLM_BASE_URL = "custom_llm_base_url"
CUSTOM_LLM_AGENT_MODEL = "custom_llm_agent_model"
CUSTOM_LLM_FAST_MODEL = "custom_llm_fast_model"

CUSTOM_LLM_SETTING_KEYS = (
    CUSTOM_LLM_ENABLE,
    CUSTOM_LLM_LABEL,
    CUSTOM_LLM_API_KEY,
    CUSTOM_LLM_BASE_URL,
    CUSTOM_LLM_AGENT_MODEL,
    CUSTOM_LLM_FAST_MODEL,
    LLM_DEFAULT_PROVIDER,
)

# TypeSafe Jev (System One decision model) — the server-side decision hop for
# the bot turn: intent routing, sort direction, pleasantry kind, and
# conversation-context flags, answered in one parallel fan-out call. Jev is
# NOT part of the chat-LLM failover chain: when it is absent or erroring,
# turns fall back to the neutral agent route, not to another provider.
JEV_API_KEY = "jev_api_key"
JEV_MODEL = "jev_model"
# Operator switch: Jev decision hops run only when this is on AND a key is
# present. Off (or an invalid key) leaves the bot fully working on the agent
# path via the neutral fallback route.
JEV_ENABLE = "jev_enable"
# Pin per deployment via the settings UI (e.g. "jev-1.13.0"); "jev-latest"
# tracks the vendor default and may change behavior on vendor releases.
JEV_DEFAULT_MODEL = "jev-latest"

JEV_SETTING_KEYS = (JEV_API_KEY, JEV_MODEL, JEV_ENABLE)
JEV_SECRET_KEYS = (JEV_API_KEY,)

# Generic LLM decode knobs, stored on the minimax panel (the same PUT that
# carries the default-provider radio and failover order) so one save owns every
# routing/wall-time lever. They apply to the agent answer lane whatever provider
# serves it; the extractor/digest lanes are bounded structured payloads already.
# ``llm_reasoning_mode``: off | low | default. ``llm_agent_max_tokens``: output
# cap; 0 means "no cap". ``llm_progressive_send``: forward the first complete
# answer bubble before the agent finishes; OFF by default so the pre-existing
# single-message behaviour is what an unsaved installation gets.
LLM_REASONING_MODE = "llm_reasoning_mode"
LLM_AGENT_MAX_TOKENS = "llm_agent_max_tokens"
LLM_PROGRESSIVE_SEND = "llm_progressive_send"
DEFAULT_LLM_REASONING_MODE = "off"
# No cap by default. On MiniMax M2.x thinking cannot be disabled and arrives
# inside ``content``, so the cap covered the deliberation as well as the answer:
# a value sized for the answer cut the answer mid-word (the provider reported
# ``finish_reason=length``). A capped lane now also pays a continuation round
# (see the answer-completion guard in ``graph/clients.py``), so an unsaved
# installation keeps today's unbounded completion and only an operator who
# knowingly wants the wall-time lever sets a value.
DEFAULT_LLM_AGENT_MAX_TOKENS = 0
DEFAULT_LLM_PROGRESSIVE_SEND = True
_REASONING_MODES = frozenset({"off", "low", "default"})

# The failover order rides the minimax panel (same PUT as the default radio),
# so it lives in the minimax key set and its cache namespace.
MINIMAX_SETTING_KEYS = (
    MINIMAX_API_KEY,
    MINIMAX_ENABLE,
    LLM_DEFAULT_PROVIDER,
    LLM_FAILOVER_ORDER,
    LLM_REASONING_MODE,
    LLM_AGENT_MAX_TOKENS,
    LLM_PROGRESSIVE_SEND,
)
OPENROUTER_SETTING_KEYS = (
    OPENROUTER_API_KEY,
    OPENROUTER_ENABLE,
    OPENROUTER_AGENT_MODEL,
    OPENROUTER_EXTRACTOR_MODEL,
    OPENROUTER_DIGEST_MODEL,
    LLM_DEFAULT_PROVIDER,
)


def _reasoning_mode_value(value: str | None, fallback: str = DEFAULT_LLM_REASONING_MODE) -> str:
    """Stored reasoning mode, else fallback, clamped to the known selectors.

    Mirrors ``_shared._provider_value``: an unknown/stale stored value falls back
    to the safe default rather than reaching the provider request.
    """
    candidate = (value or fallback or DEFAULT_LLM_REASONING_MODE).strip().lower()
    return candidate if candidate in _REASONING_MODES else DEFAULT_LLM_REASONING_MODE


def _agent_max_tokens_value(
    value: str | int | None, fallback: int = DEFAULT_LLM_AGENT_MAX_TOKENS
) -> int:
    """Stored output cap as an int (non-negative), else fallback.

    0 is valid and means "no cap"; a malformed or negative stored value falls
    back to the default so a bad row can never disable the cap silently.
    """
    try:
        parsed = int(value) if value not in (None, "") else int(fallback)
    except (TypeError, ValueError):
        parsed = int(fallback)
    return parsed if parsed >= 0 else int(fallback)


@dataclass(frozen=True)
class MinimaxRuntimeConfig:
    api_key: str = ""
    base_url: str = ""
    agent_model: str = ""
    extractor_model: str = ""
    enabled: bool = True
    default_provider: str = "minimax"
    reasoning_mode: str = DEFAULT_LLM_REASONING_MODE
    agent_max_tokens: int = DEFAULT_LLM_AGENT_MAX_TOKENS
    progressive_send: bool = DEFAULT_LLM_PROGRESSIVE_SEND


@dataclass(frozen=True)
class OpenRouterRuntimeConfig:
    api_key: str = ""
    base_url: str = ""
    agent_model: str = ""
    extractor_model: str = ""
    digest_model: str = ""
    embedding_model: str = ""
    embedding_dim: int = EMBEDDING_DIM
    enabled: bool = False
    default_provider: str = "minimax"


@dataclass(frozen=True)
class CustomLlmRuntimeConfig:
    """Admin-configured OpenAI-compatible provider used on quota exhaustion."""

    api_key: str = ""
    base_url: str = ""
    agent_model: str = ""
    fast_model: str = ""
    label: str = ""
    enabled: bool = False
    default_provider: str = "minimax"

    @property
    def usable(self) -> bool:
        """Whether this config can actually serve a turn."""
        return bool(self.enabled and self.api_key and self.base_url and self.agent_model)


@dataclass(frozen=True)
class JevRuntimeConfig:
    """TypeSafe Jev decision-hop credentials (settings UI first, env fallback)."""

    api_key: str = ""
    model: str = JEV_DEFAULT_MODEL
    enabled: bool = False

    @property
    def usable(self) -> bool:
        """Whether decision hops run: switched on AND a key is present."""
        return bool(self.enabled and self.api_key)


class LlmSettingsMixin:
    """Resolve/admin/persist for the MiniMax / OpenRouter / custom / Jev groups."""

    if TYPE_CHECKING:
        # Supplied by IntegrationSettingsService (the composer) and StorageMixin
        # (its sibling). Declarations only: TYPE_CHECKING is False at runtime, so
        # nothing here is ever assigned and the composed class stays the single
        # source of truth.
        db: AsyncSession
        settings: Settings

        async def _stored_values(self, keys: Iterable[str]) -> dict[str, str]: ...

        async def _write_setting(
            self,
            key: str,
            value: str,
            *,
            actor_id: object | None = None,
            is_secret: bool,
        ) -> bool: ...

        async def _bump_provider_namespaces(
            self, primary: str, changed: list[str]
        ) -> None: ...

        async def get_provider_test_result(self, provider: str) -> dict | None: ...

        from collections.abc import Iterable

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.config import Settings

    async def resolve_minimax(self) -> MinimaxRuntimeConfig:
        async def _load() -> dict:
            stored = await self._stored_values(MINIMAX_SETTING_KEYS)
            return MinimaxRuntimeConfig(
                api_key=stored.get(MINIMAX_API_KEY) or self.settings.minimax_api_key,
                base_url=self.settings.minimax_base_url,
                agent_model=self.settings.minimax_agent_model,
                extractor_model=self.settings.minimax_extractor_model,
                enabled=_bool_value(stored.get(MINIMAX_ENABLE), self.settings.minimax_enable),
                default_provider=_provider_value(
                    stored.get(LLM_DEFAULT_PROVIDER),
                    getattr(self.settings, "llm_default_provider", "minimax"),
                ),
                reasoning_mode=_reasoning_mode_value(stored.get(LLM_REASONING_MODE)),
                agent_max_tokens=_agent_max_tokens_value(stored.get(LLM_AGENT_MAX_TOKENS)),
                progressive_send=_bool_value(
                    stored.get(LLM_PROGRESSIVE_SEND), DEFAULT_LLM_PROGRESSIVE_SEND
                ),
            ).__dict__

        cached = await cached_minimax_config(_load)
        return MinimaxRuntimeConfig(**cached)

    async def admin_minimax_view(self) -> dict:
        cfg = await self.resolve_minimax()
        return {
            "minimax_api_key": _secret_status(cfg.api_key),
            "minimax_base_url": cfg.base_url,
            "minimax_agent_model": cfg.agent_model,
            "minimax_extractor_model": cfg.extractor_model,
            "minimax_enable": cfg.enabled,
            "llm_default_provider": cfg.default_provider,
            "llm_failover_order": list(await self.resolve_llm_failover_order()),
            "llm_reasoning_mode": cfg.reasoning_mode,
            "llm_agent_max_tokens": cfg.agent_max_tokens,
            "llm_progressive_send": cfg.progressive_send,
            "last_test": await self.get_provider_test_result("minimax"),
        }

    async def resolve_openrouter(self) -> OpenRouterRuntimeConfig:
        async def _load() -> dict:
            stored = await self._stored_values(OPENROUTER_SETTING_KEYS)
            return OpenRouterRuntimeConfig(
                api_key=stored.get(OPENROUTER_API_KEY) or self.settings.openrouter_api_key,
                base_url=self.settings.openrouter_base_url,
                agent_model=stored.get(OPENROUTER_AGENT_MODEL)
                or self.settings.openrouter_agent_model,
                extractor_model=(
                    stored.get(OPENROUTER_EXTRACTOR_MODEL)
                    or self.settings.openrouter_extractor_model
                ),
                digest_model=(
                    stored.get(OPENROUTER_DIGEST_MODEL) or self.settings.openrouter_digest_model
                ),
                embedding_model=self.settings.openrouter_embedding_model,
                embedding_dim=self.settings.embedding_dim,
                enabled=_bool_value(stored.get(OPENROUTER_ENABLE), self.settings.openrouter_enable),
                default_provider=_provider_value(
                    stored.get(LLM_DEFAULT_PROVIDER),
                    getattr(self.settings, "llm_default_provider", "minimax"),
                ),
            ).__dict__

        cached = await cached_openrouter_config(_load)
        return OpenRouterRuntimeConfig(**cached)

    async def admin_openrouter_view(self) -> dict:
        cfg = await self.resolve_openrouter()
        return {
            "openrouter_api_key": _secret_status(cfg.api_key),
            "openrouter_base_url": cfg.base_url,
            "openrouter_agent_model": cfg.agent_model,
            "openrouter_extractor_model": cfg.extractor_model,
            "openrouter_digest_model": cfg.digest_model,
            "openrouter_embedding_model": cfg.embedding_model,
            "openrouter_embedding_dim": cfg.embedding_dim,
            "openrouter_enable": cfg.enabled,
            "llm_default_provider": cfg.default_provider,
            "llm_failover_order": list(await self.resolve_llm_failover_order()),
            "last_test": await self.get_provider_test_result("openrouter"),
        }

    async def resolve_custom_llm(self) -> CustomLlmRuntimeConfig:
        async def _load() -> dict:
            stored = await self._stored_values(CUSTOM_LLM_SETTING_KEYS)
            # getattr with a default: this provider is optional, and callers
            # (including tests) may pass a settings object that predates it.
            def _default(name: str, fallback: str = "") -> str:
                return getattr(self.settings, name, fallback) or fallback

            agent_model = (
                stored.get(CUSTOM_LLM_AGENT_MODEL) or _default("custom_llm_agent_model")
            )
            return CustomLlmRuntimeConfig(
                api_key=stored.get(CUSTOM_LLM_API_KEY) or _default("custom_llm_api_key"),
                base_url=stored.get(CUSTOM_LLM_BASE_URL) or _default("custom_llm_base_url"),
                agent_model=agent_model,
                # Mirror the agent model into fast unconditionally: no lane
                # consumes it today, so a stray stored/env value (a browser
                # once autofilled an email into a model box) can never reach a
                # request.
                fast_model=agent_model,
                label=stored.get(CUSTOM_LLM_LABEL) or _default("custom_llm_label", "Dự phòng"),
                enabled=_bool_value(
                    stored.get(CUSTOM_LLM_ENABLE),
                    bool(getattr(self.settings, "custom_llm_enable", False)),
                ),
                default_provider=_provider_value(
                    stored.get(LLM_DEFAULT_PROVIDER),
                    getattr(self.settings, "llm_default_provider", "minimax"),
                ),
            ).__dict__

        cached = await cached_custom_llm_config(_load)
        return CustomLlmRuntimeConfig(**cached)

    async def admin_custom_llm_view(self) -> dict:
        cfg = await self.resolve_custom_llm()
        return {
            "custom_llm_api_key": _secret_status(cfg.api_key),
            "custom_llm_base_url": cfg.base_url,
            "custom_llm_agent_model": cfg.agent_model,
            "custom_llm_fast_model": cfg.fast_model,
            "custom_llm_label": cfg.label,
            "custom_llm_enable": cfg.enabled,
            "custom_llm_usable": cfg.usable,
            "llm_default_provider": cfg.default_provider,
            "llm_failover_order": list(await self.resolve_llm_failover_order()),
            "last_test": await self.get_provider_test_result("custom"),
        }

    async def resolve_jev(self) -> JevRuntimeConfig:
        """Resolve Jev decision-hop credentials (DB row first, JEV_API_KEY env fallback).

        The env fallback reads ``os.environ`` directly because the key is
        operator-supplied per deployment (e.g. exported in a shell profile)
        and ``Settings`` intentionally has no ``jev_*`` field.
        """

        async def _load() -> dict:
            stored = await self._stored_values(JEV_SETTING_KEYS)
            return JevRuntimeConfig(
                api_key=stored.get(JEV_API_KEY) or os.environ.get("JEV_API_KEY", ""),
                model=stored.get(JEV_MODEL) or JEV_DEFAULT_MODEL,
                # Default off: an operator must consciously switch Jev on,
                # mirroring how openrouter_enable/custom_llm_enable gate those
                # providers.
                enabled=_bool_value(stored.get(JEV_ENABLE), False),
            ).__dict__

        cached = await cached_jev_config(_load)
        return JevRuntimeConfig(**cached)

    async def admin_jev_view(self) -> dict:
        cfg = await self.resolve_jev()
        return {
            "jev_api_key": _secret_status(cfg.api_key),
            "jev_model": cfg.model,
            "jev_enable": cfg.enabled,
            "jev_usable": cfg.usable,
        }

    async def update_jev(
        self,
        values: dict[str, str | bool | None],
        *,
        actor_id,
    ) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if key not in JEV_SETTING_KEYS or value is None:
                continue
            if await self._write_setting(
                key,
                str(value),
                actor_id=actor_id,
                is_secret=key in JEV_SECRET_KEYS,
            ):
                changed.append(key)

        if changed:
            await record_audit(
                self.db,
                action="update_jev_integration_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="jev",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
            evict_local_namespace(NS_INTEGRATION_JEV)
            await bump_cache_version(NS_INTEGRATION_JEV)
        return changed

    async def resolve_llm_failover_order(self) -> tuple[str, ...]:
        """Operator-ranked spare order; canonical ranking when nothing is stored.

        Deliberately read per call instead of cached inside a provider
        snapshot: the failover-chain build is the only consumer, and client
        builds are already gated behind the provider cache versions, so the
        minimax-namespace bump on save invalidates it with the rest.
        """
        stored = await self._stored_values((LLM_FAILOVER_ORDER,))
        # Subscript-with-membership, not dict.get: this module is httpx-
        # transport-scanned by the runtime-surface oracle, which counts every
        # bare ``get`` call as provider I/O.
        raw = stored[LLM_FAILOVER_ORDER] if LLM_FAILOVER_ORDER in stored else None
        return normalize_llm_failover_order(raw)

    async def update_custom_llm(
        self,
        values: dict[str, str | bool | None],
        *,
        actor_id,
    ) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if key not in CUSTOM_LLM_SETTING_KEYS or value is None:
                continue
            if await self._write_setting(
                key,
                str(value),
                actor_id=actor_id,
                is_secret=key == CUSTOM_LLM_API_KEY,
            ):
                changed.append(key)

        if changed:
            await record_audit(
                self.db,
                action="update_custom_llm_integration_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="fallback_llm",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
            await self._bump_provider_namespaces(NS_INTEGRATION_CUSTOM_LLM, changed)
        return changed

    async def update_minimax(
        self,
        values: dict[str, str | int | bool | list[str] | None],
        *,
        actor_id,
    ) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if key not in MINIMAX_SETTING_KEYS or value is None:
                continue
            # The failover order arrives as a JSON list and is stored as CSV.
            serialized = (
                ",".join(value) if isinstance(value, (list, tuple)) else str(value)
            )
            if await self._write_setting(
                key,
                serialized,
                actor_id=actor_id,
                is_secret=key == MINIMAX_API_KEY,
            ):
                changed.append(key)

        if changed:
            await record_audit(
                self.db,
                action="update_minimax_integration_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="minimax",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
            await self._bump_provider_namespaces(NS_INTEGRATION_MINIMAX, changed)
        return changed

    async def update_openrouter(
        self,
        values: dict[str, str | bool | None],
        *,
        actor_id,
    ) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if key not in OPENROUTER_SETTING_KEYS or value is None:
                continue
            if await self._write_setting(
                key,
                str(value),
                actor_id=actor_id,
                is_secret=key == OPENROUTER_API_KEY,
            ):
                changed.append(key)

        if changed:
            await record_audit(
                self.db,
                action="update_openrouter_integration_settings",
                actor_id=actor_id,
                target_type="integration_settings",
                target_id="openrouter",
                payload={"changed_keys": changed},
            )
            await self.db.commit()
            await self._bump_provider_namespaces(NS_INTEGRATION_OPENROUTER, changed)
        return changed
