"""LLM provider probes for the admin test endpoints.

One real chat completion per provider (plus the persisted outcome rows) so
"configured" and "actually works" stay distinct facts. Extracted from the
admin integrations router; the transport layer only parses the request body
and maps the result onto the response model.
"""

from __future__ import annotations

import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.integrations import (
    CustomLlmIntegrationTestOut,
    CustomLlmProbeIn,
    JevIntegrationTestOut,
    JevIntegrationSettingsUpdate,
    MinimaxIntegrationTestOut,
    OpenRouterIntegrationTestOut,
)
from app.services.integration_settings import IntegrationSettingsService


async def probe_and_record(
    db: AsyncSession,
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    missing: list[str],
    persist: bool,
) -> dict:
    """Run ONE real chat completion against a provider and persist the outcome.

    Replaces the old key-presence checks: "configured" and "actually works"
    become distinct facts. Both pass and fail are persisted (a dead provider
    must keep showing its error), so the settings page can render
    "tested 2 minutes ago | 412 ms" across reloads. persist=False probes
    operator-typed values that are not saved yet.
    """
    if missing:
        return {
            "ok": False,
            "configured": False,
            "missing": missing,
            "latency_ms": None,
            "sample": None,
            "error": None,
        }
    from app.services.llm_probe import probe_openai_compatible_chat

    probe = await probe_openai_compatible_chat(
        api_key=api_key, base_url=base_url, model=model
    )
    if persist:
        await IntegrationSettingsService(db).record_provider_test_result(
            provider,
            {
                "ok": probe.ok,
                "latency_ms": probe.latency_ms,
                "tested_at": int(time.time()),
                "error": probe.error,
            },
        )
    return {
        "ok": probe.ok,
        "configured": True,
        "missing": [],
        "latency_ms": probe.latency_ms,
        "sample": probe.sample,
        "error": probe.error,
    }


async def probe_minimax(db: AsyncSession) -> MinimaxIntegrationTestOut:
    cfg = await IntegrationSettingsService(db).resolve_minimax()
    missing = [] if cfg.api_key else ["minimax_api_key"]
    result = await probe_and_record(
        db,
        provider="minimax",
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.agent_model,
        missing=missing,
        persist=True,
    )
    return MinimaxIntegrationTestOut(
        configured=result["configured"],
        missing=result["missing"],
        ok=result["ok"],
        latency_ms=result["latency_ms"],
        sample=result["sample"],
        error=result["error"],
    )


async def probe_openrouter(db: AsyncSession) -> OpenRouterIntegrationTestOut:
    cfg = await IntegrationSettingsService(db).resolve_openrouter()
    missing = [] if cfg.api_key else ["openrouter_api_key"]
    result = await probe_and_record(
        db,
        provider="openrouter",
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.agent_model,
        missing=missing,
        persist=True,
    )
    return OpenRouterIntegrationTestOut(
        configured=result["configured"],
        missing=result["missing"],
        ok=result["ok"],
        latency_ms=result["latency_ms"],
        sample=result["sample"],
        error=result["error"],
    )


async def probe_custom_llm(
    body: CustomLlmProbeIn | None, db: AsyncSession
) -> CustomLlmIntegrationTestOut:
    """Make a real chat call against the failover provider.

    Unlike the minimax/openrouter probes, which only assert a key is present,
    this sends an actual minimal completion. A provider that is unreachable,
    rejects the credential, or does not know the model id must fail here rather
    than during a live candidate conversation.

    Credentials may be supplied in the body so they can be validated BEFORE
    being saved; anything omitted falls back to the stored configuration.
    """
    stored = await IntegrationSettingsService(db).resolve_custom_llm()
    supplied = body.model_dump(exclude_unset=True) if body is not None else {}
    api_key = supplied.get("custom_llm_api_key") or stored.api_key
    base_url = supplied.get("custom_llm_base_url") or stored.base_url
    model = supplied.get("custom_llm_agent_model") or stored.agent_model

    missing = [
        name
        for name, value in (
            ("custom_llm_api_key", api_key),
            ("custom_llm_base_url", base_url),
            ("custom_llm_agent_model", model),
        )
        if not value
    ]
    if missing:
        return CustomLlmIntegrationTestOut(ok=False, configured=False, missing=missing)

    # Transparence: when the probe runs on the STORED token (nothing typed),
    # a failure must say which token was used - a silent stored-junk key was
    # exactly the confusion this endpoint could not explain before.
    used_stored_key = not supplied.get("custom_llm_api_key")
    persist = not supplied  # probing saved config records history; typed values are not config yet
    result = await probe_and_record(
        db,
        provider="custom",
        api_key=api_key,
        base_url=base_url,
        model=model,
        missing=[],
        persist=persist,
    )
    error = result["error"]
    if used_stored_key and not result["ok"]:
        error = (
            f"{error or 'Kiểm tra thất bại'}"
            " — Access Token đã lưu bị từ chối. Nhập lại Access Token rồi bấm Lưu thay đổi."
        )

    return CustomLlmIntegrationTestOut(
        ok=result["ok"],
        configured=True,
        missing=[],
        latency_ms=result["latency_ms"],
        sample=result["sample"],
        error=error,
    )


async def probe_jev(
    body: JevIntegrationSettingsUpdate | None, db: AsyncSession
) -> JevIntegrationTestOut:
    """Make a real systemone call so a bad key fails here, not in a live turn.

    Credentials may be supplied in the body so they can be validated BEFORE
    being saved; anything omitted falls back to the stored configuration.
    """
    from app.services.llm_probe import probe_typesafe_systemone

    stored = await IntegrationSettingsService(db).resolve_jev()
    supplied = body.model_dump(exclude_unset=True) if body is not None else {}
    api_key = supplied.get("jev_api_key") or stored.api_key
    model = supplied.get("jev_model") or stored.model

    missing = [
        name
        for name, value in (("jev_api_key", api_key), ("jev_model", model))
        if not value
    ]
    if missing:
        return JevIntegrationTestOut(ok=False, configured=False, missing=missing)

    result = await probe_typesafe_systemone(api_key=api_key, model=model)
    return JevIntegrationTestOut(
        ok=result["ok"],
        configured=True,
        missing=[],
        latency_ms=result["latency_ms"],
        sample=result["sample"],
        error=result["error"],
    )
