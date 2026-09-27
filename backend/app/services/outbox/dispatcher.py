"""Provider dispatch for the outbound transactional outbox.

The only part of the outbox that talks to providers: it claims a PENDING
command through :mod:`app.services.outbox.repository`, verifies the
installation-runtime authority fence, and routes the command either through the
neutral channel registry or the legacy :class:`ZaloChannelSender`.

The SENDING claim is committed before provider I/O. If the process dies after
provider acceptance but before finalization, recovery therefore sees SENDING and
terminalizes it as SEND_UNKNOWN instead of resending it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxStatus, OutboundOutbox
from app.services.outbox.recipient_marks import (
    SEND_UNREACHABLE_ERROR_CLASS,
    is_recipient_unreachable,
    mark_recipient_unreachable,
)
from app.services.outbox.repository import DispatchCandidate, DispatchResult
from app.shared.application.outbound import OutboundPolicySuppressedError


def _facade():
    """Return the ``app.services.outbox_service`` facade module.

    ``outbox_service`` re-exports this module's surface. Callers and the test
    suite monkeypatch ``app.services.outbox_service.claim_pending_outbox`` and
    ``app.services.outbox_service._try_neutral_dispatch`` and expect the patched
    object to be the one this module calls, so those two collaborators are
    resolved through the facade at call time. Binding them at import time would
    silently ignore the patch after the repository/dispatcher split.
    """
    from app.services import outbox_service

    return outbox_service


async def _refresh_oa_access_token_for_dispatch(
    integration_settings,
    *,
    revalidate=None,
    account_key: str | None = None,
) -> str | None:
    """Rotate one OA account's credentials and restore the send fence.

    Token rotation commits its database session. Runtime-bound callers therefore
    supply a revalidator that reacquires the shared authority lock and checks the
    stamp before the OA adapter is allowed to retry provider I/O. ``account_key``
    selects the OA whose single-use refresh token is redeemed; the original OA
    is the default.
    """

    new_token = await integration_settings.refresh_oa_access_token(account_key)
    if new_token is None:
        return None
    if revalidate is not None and not await revalidate():
        raise OutboundPolicySuppressedError
    return new_token


async def dispatch_outbox(db: AsyncSession, *, outbox_id: int) -> DispatchResult | None:
    """Claim, authorize, and send an immutable command.

    The SENDING claim is committed before provider I/O. If the process dies
    after provider acceptance but before finalization, recovery therefore sees
    SENDING and terminalizes it as SEND_UNKNOWN instead of resending it.

    Runtime-bound commands validate authority while holding the shared advisory
    lock both before and after that commit. The post-commit check closes the
    activation window created when the durable claim releases its transaction
    lock; the second shared lock remains held through provider I/O and caller
    finalization.

    Only a PENDING row is claimable here — ``claim_pending_outbox`` is the
    single-sender guarantee, so a command another sender already claimed is
    never sent from this entry point. A command the caller itself claimed is
    sent through :func:`dispatch_message_outbox`.
    """
    outbox = await db.get(OutboundOutbox, outbox_id)
    if outbox is None or outbox.status != OutboxStatus.PENDING.value:
        return None

    authority, authority_is_current = await _resolve_runtime_authority(db, outbox)
    if not authority_is_current:
        # Claim the row anyway so this attempt — not a later sweep — owns the
        # terminal write; the suppression is the recorded outcome.
        candidate = await _facade().claim_pending_outbox(db, outbox_id=outbox_id)
        if candidate is None:
            return None
        await db.commit()
        return _suppressed_dispatch_result(candidate)

    candidate = await _facade().claim_pending_outbox(db, outbox_id=outbox_id)
    if candidate is None:
        return None
    await db.commit()
    return await _dispatch_claimed_command(
        db, outbox=outbox, candidate=candidate, authority=authority
    )


async def _dispatch_claimed_command(
    db: AsyncSession,
    *,
    outbox: OutboundOutbox,
    candidate: DispatchCandidate,
    authority: _RuntimeAuthority,
) -> DispatchResult:
    """Send an already-claimed command and project the provider result.

    Shared by the dispatcher claim path and the inline bot turn that claims its
    own command inside ``claim_send`` (REL-06). The runtime-authority fence is
    re-verified here, under the shared lock, because the claim commit released
    the transaction-scoped lock.
    """
    if not await authority.reacquire_and_verify():
        return _suppressed_dispatch_result(candidate)

    recipient_id = str(candidate.payload.get("chat_id") or "")
    if recipient_id and await is_recipient_unreachable(candidate.channel, recipient_id):
        # The provider already stated this recipient can never receive a message
        # (user_unreachable). A send is guaranteed to fail, so skip provider I/O
        # and terminalize the command as suppressed; the finalizer records the
        # conversation's opt-out from the user_unreachable error class.
        return DispatchResult(
            outbox_id=candidate.outbox_id,
            message_id=candidate.message_id,
            ok=False,
            error="recipient terminally unreachable",
            error_class=SEND_UNREACHABLE_ERROR_CLASS,
            suppressed=True,
        )

    from app.services.integration_settings import IntegrationSettingsService
    from app.services.zalo_sender import ZaloChannelSender

    integration_settings = IntegrationSettingsService(db)
    # Multi-OA: send as the OA that owns this conversation's identity. Only the
    # OA channel has accounts to resolve — the Bot and Messenger paths skip the
    # lookup entirely and keep their behaviour (and their query count).
    account_key = (
        await _zalo_account_key_for_message(db, candidate.message_id)
        if candidate.channel == "zalo_oa"
        else None
    )
    cfg = await integration_settings.resolve_zalo(account_key)

    async def refresh_oa_access_token() -> str | None:
        return await _refresh_oa_access_token_for_dispatch(
            integration_settings,
            revalidate=authority.reacquire_and_verify,
            account_key=account_key,
        )

    # Channel-neutral dispatch path (Phase 3): route through the registry when
    # the outbox channel maps to a registered provider. Falls back to the legacy
    # ZaloChannelSender for payloads that do not (e.g. a yet-unmapped channel).
    try:
        dispatch_result = await _facade()._try_neutral_dispatch(
            db,
            candidate,
            outbox,
            cfg,
            integration_settings,
            refresh_oa_access_token,
            account_key=account_key,
        )
        if dispatch_result is not None:
            await _mark_unreachable_recipient(candidate, dispatch_result.error_class)
            return dispatch_result

        # Legacy path: direct ZaloChannelSender (unchanged behavior).
        sender = ZaloChannelSender(
            cfg,
            refresh=refresh_oa_access_token,
        )
        result = await sender.send_payload(candidate.channel, candidate.payload)
    except OutboundPolicySuppressedError:
        return _suppressed_dispatch_result(
            candidate, error="runtime authority changed during OA credential refresh"
        )
    dispatch_result = DispatchResult(
        outbox_id=candidate.outbox_id,
        message_id=candidate.message_id,
        ok=result.ok,
        zalo_message_id=result.msg_id,
        error=result.error,
        error_class=result.error_class,
        telemetry=result.telemetry,
    )
    await _mark_unreachable_recipient(candidate, dispatch_result.error_class)
    return dispatch_result


async def _mark_unreachable_recipient(
    candidate: DispatchCandidate, error_class: str | None
) -> None:
    """Record a terminal recipient mark after a send fails as unreachable.

    Keyed by the outbox command's channel identity so the turn path / dispatcher
    sweep can skip generating or sending to it within the marker TTL.
    """
    if error_class != SEND_UNREACHABLE_ERROR_CLASS:
        return
    recipient_id = str(candidate.payload.get("chat_id") or "")
    if recipient_id:
        await mark_recipient_unreachable(candidate.channel, recipient_id)


@dataclass(frozen=True)
class _RuntimeAuthority:
    """Resolved installation-runtime authority fence for one outbound command.

    ``stamp`` is None for commands that carry no runtime stamp (legacy rows and
    non-runtime channels): there is nothing to verify, so every check passes.
    """

    stamp: Any | None = None
    repository: Any | None = None
    service: Any | None = None

    async def reacquire_and_verify(self) -> bool:
        """Re-check the stamp while holding the shared advisory lock.

        Any commit in between (the durable claim, an OA token refresh) releases
        the transaction-scoped lock, so authority must be re-verified
        immediately before provider I/O resumes.
        """
        if self.stamp is None:
            return True
        assert self.repository is not None and self.service is not None
        await self.repository.acquire_runtime_dispatch_lock()
        return await self.service.runtime_stamp_is_current(self.stamp)


async def _resolve_runtime_authority(
    db: AsyncSession, outbox: OutboundOutbox
) -> tuple[_RuntimeAuthority, bool]:
    """Resolve the runtime fence for ``outbox``; return ``(authority, is_current)``.

    ``is_current`` is False when the command is runtime-bound but its stamp is
    incomplete or no longer the active installation revision — the caller
    records a suppression instead of sending.
    """
    if outbox.fence_scope != "RUNTIME":
        return _RuntimeAuthority(), True

    from app.services.installation.authority import RuntimeAuthorityStamp
    from app.services.installation.repository import InstallationRepository
    from app.services.installation.service import InstallationService

    repository = InstallationRepository(db)
    service = InstallationService(db)
    await repository.acquire_runtime_dispatch_lock()
    stamp_complete = (
        outbox.runtime_revision_id is not None
        and outbox.authority_generation is not None
        and outbox.runtime_fingerprint is not None
    )
    stamp = (
        RuntimeAuthorityStamp(
            revision_id=outbox.runtime_revision_id,
            authority_generation=outbox.authority_generation,
            fingerprint=outbox.runtime_fingerprint,
        )
        if stamp_complete
        else None
    )
    is_current = stamp is not None and await service.runtime_stamp_is_current(stamp)
    return _RuntimeAuthority(stamp=stamp, repository=repository, service=service), is_current


def _suppressed_dispatch_result(
    candidate: DispatchCandidate,
    *,
    error: str = "runtime authority changed before outbound dispatch",
) -> DispatchResult:
    """Project an authority suppression onto the shared dispatch result."""
    return DispatchResult(
        outbox_id=candidate.outbox_id,
        message_id=candidate.message_id,
        ok=False,
        error=error,
        error_class="policy_suppressed",
        suppressed=True,
    )


async def _zalo_account_key_for_message(db: AsyncSession, message_id: int | None) -> str | None:
    """The ``zalo_oa`` account key owning one message's conversation, or ``None``.

    ``None`` means "not an OA conversation" (Bot, Messenger, unresolved) and
    makes every caller fall back to the original OA's credentials.
    """
    if message_id is None:
        return None
    from sqlalchemy import select

    from app.channels import types as ct
    from app.models.contact import ContactChannelIdentity
    from app.models.conversation import Conversation, Message

    row = (
        await db.execute(
            select(ContactChannelIdentity.provider, ContactChannelIdentity.account_key)
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .join(
                ContactChannelIdentity,
                Conversation.channel_identity_id == ContactChannelIdentity.id,
            )
            .where(Message.id == message_id)
        )
    ).first()
    if row is None or row.provider != ct.PROVIDER_ZALO_OA:
        return None
    return row.account_key


async def _try_neutral_dispatch(
    db: AsyncSession,
    candidate: DispatchCandidate,
    outbox: OutboundOutbox,
    cfg,
    integration_settings,
    oa_refresh,
    *,
    account_key: str | None = None,
) -> DispatchResult | None:
    """Attempt registry-driven dispatch; return None to fall back to legacy.

    Builds an :class:`OutboundTextCommand` from the outbox row's Zalo-shaped
    payload (``chat_id``/``text``/``quote_message_id``) and routes it through
    :class:`ChannelDispatchService`. The authority fence uses the outbox row's
    ``channel_account_generation`` when present (Phase 2 column).
    """
    from app.channels import types as ct
    from app.channels.dispatch import (
        ChannelDispatchService,
        build_zalo_registry_from_config,
    )
    from app.channels.registry import ChannelAdapterRegistry

    provider = _provider_for_outbox_channel(candidate.channel)
    if provider is None:
        return None  # unmapped channel → legacy path

    if provider == ct.PROVIDER_FACEBOOK_MESSENGER:
        # Messenger: resolve the active Page config + account_key from the
        # conversation's channel identity. The Page token is decrypted
        # server-side via the FacebookAccountResolver.
        return await _dispatch_facebook(
            db, candidate, outbox, integration_settings
        )

    # Zalo path: build a Zalo registry from the resolved config. Its OA adapter
    # carries the token of the account the caller resolved (the conversation's
    # own OA on a multi-OA deployment; the original OA otherwise).
    registry: ChannelAdapterRegistry = build_zalo_registry_from_config(
        cfg,
        oa_refresh=oa_refresh,
        oa_account_key=account_key or "",
    )
    if registry.get(provider) is None:
        return None  # adapter not registered → legacy path

    text = str(candidate.payload.get("text") or "")
    recipient_id = str(candidate.payload.get("chat_id") or "")
    if not text or not recipient_id:
        return DispatchResult(
            outbox_id=candidate.outbox_id,
            message_id=candidate.message_id,
            ok=False,
            error="outbound payload is missing chat_id or text",
            error_class="provider_error",
        )

    if provider == ct.PROVIDER_ZALO_OA:
        account_key = account_key or "default:zalo_oa"
    else:
        account_key = "default:zalo_bot"

    # NOTE(Phase 4): legacy rows have channel_account_generation = NULL → coerced
    # to 0 here. That is safe today because ChannelDispatchService is wired with
    # account_resolver=None (the fence is skipped). The moment a resolver is
    # wired, every legacy row will compare account.generation (≥1, from Alembic
    # 0047) > 0 and be suppressed. Before wiring the resolver, either stamp
    # channel_account_generation on create_pending_outbox or run a one-shot
    # backfill re-stamping existing PENDING rows with the current generation.
    command = ct.OutboundTextCommand(
        provider=provider,
        account_key=account_key,
        recipient_id=recipient_id,
        text=text,
        channel_account_generation=int(outbox.channel_account_generation or 0),
        reply_to_message_id=candidate.payload.get("quote_message_id") or None,
    )
    svc = ChannelDispatchService(registry)
    result = await svc.send(command)
    return DispatchResult(
        outbox_id=candidate.outbox_id,
        message_id=candidate.message_id,
        ok=result.ok,
        zalo_message_id=result.provider_message_id,
        provider_message_id=result.provider_message_id,
        error=result.error,
        error_class=result.error_class,
        suppressed=result.suppressed,
        telemetry=result.telemetry,
    )


async def _dispatch_facebook(
    db: AsyncSession,
    candidate: DispatchCandidate,
    outbox: OutboundOutbox,
    integration_settings,
) -> DispatchResult | None:
    """Dispatch a Messenger outbound command through the neutral registry.

    Resolves the active Page config (decrypting the Page token server-side),
    the account_key + recipient from the conversation's channel identity, and
    wires the :class:`FacebookAccountResolver` so the channel-account authority
    fence (generation check) is enforced — a stale command queued across a
    Page disconnect/reconnect is suppressed rather than sent.
    """
    from app.channels import types as ct
    from app.channels.dispatch import ChannelDispatchService, build_facebook_registry
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        acquire_facebook_page_authority_lock,
    )

    # 1. Resolve the conversation → channel identity → account key, recipient,
    #    and authoritative last inbound timestamp for Messenger policy.
    from app.models.conversation import Conversation, Message
    from app.models.contact import ContactChannelIdentity
    from sqlalchemy import select

    msg = await db.get(Message, candidate.message_id)
    if msg is None:
        return None
    row = (
        await db.execute(
            select(
                ContactChannelIdentity.account_key,
                ContactChannelIdentity.external_id,
                Conversation.last_inbound_at,
            )
            .select_from(Conversation)
            .join(
                ContactChannelIdentity,
                Conversation.channel_identity_id == ContactChannelIdentity.id,
            )
            .where(Conversation.id == msg.conversation_id)
        )
    ).first()
    if row is None:
        return None  # no identity → legacy path cannot help either; suppress
    account_key, recipient_id = row.account_key, row.external_id

    # 2. Enforce Meta's standard messaging window before resolving credentials
    #    or reaching provider I/O. V1 deliberately supports no message tags.
    from app.channels.providers.facebook_policy import evaluate_send_eligibility

    policy = evaluate_send_eligibility(last_inbound_at=row.last_inbound_at)
    if not policy.allowed:
        error = (
            "messenger standard messaging window expired"
            if policy.reason == "window_expired"
            else "messenger standard messaging window is not open"
        )
        return DispatchResult(
            outbox_id=candidate.outbox_id,
            message_id=candidate.message_id,
            ok=False,
            error=error,
            error_class="policy_suppressed",
            suppressed=True,
        )

    # Hold shared Page authority from credential resolution through provider I/O.
    # Connect/reconnect/disconnect take the matching exclusive lock, so no stale
    # token or generation can cross the final validation-to-send boundary.
    await acquire_facebook_page_authority_lock(db, shared=True)

    # 3. Resolve the active Page config. resolve_facebook decrypts the Page
    #    token with the page_id-bound AEAD context (Phase 4).
    fb_cfg = await integration_settings.resolve_facebook(account_key)
    if fb_cfg is None:
        return DispatchResult(
            outbox_id=candidate.outbox_id,
            message_id=candidate.message_id,
            ok=False,
            error="facebook page token not resolvable (reconnect required)",
            error_class="auth_revoked",
            suppressed=True,
        )

    text = str(candidate.payload.get("text") or "")
    if not text:
        return DispatchResult(
            outbox_id=candidate.outbox_id,
            message_id=candidate.message_id,
            ok=False,
            error="outbound payload is missing text",
            error_class="provider_error",
        )

    registry = build_facebook_registry(fb_cfg)
    resolver = FacebookAccountResolver(db)
    command = ct.OutboundTextCommand(
        provider=ct.PROVIDER_FACEBOOK_MESSENGER,
        account_key=account_key,
        recipient_id=recipient_id,
        text=text,
        channel_account_generation=int(outbox.channel_account_generation or 0),
        reply_to_message_id=candidate.payload.get("quote_message_id") or None,
    )
    svc = ChannelDispatchService(registry, account_resolver=resolver)

    def final_policy_guard() -> ct.ChannelSendResult | None:
        policy = evaluate_send_eligibility(last_inbound_at=row.last_inbound_at)
        if policy.allowed:
            return None
        error = (
            "messenger standard messaging window expired"
            if policy.reason == "window_expired"
            else "messenger standard messaging window is not open"
        )
        return ct.ChannelSendResult(
            ok=False,
            error=error,
            error_class="policy_suppressed",
            suppressed=True,
        )

    result = await svc.send(command, before_provider_io=final_policy_guard)
    return DispatchResult(
        outbox_id=candidate.outbox_id,
        message_id=candidate.message_id,
        ok=result.ok,
        zalo_message_id=result.provider_message_id,
        provider_message_id=result.provider_message_id,
        error=result.error,
        error_class=result.error_class,
        suppressed=result.suppressed,
        telemetry=result.telemetry,
    )


def _provider_for_outbox_channel(channel: str) -> str | None:
    """Map the outbox row's channel string to a neutral provider id.

    The outbox ``channel`` column carries provider ids directly
    (``zalo_bot`` / ``zalo_oa`` / ``facebook_messenger``). Returns ``None`` for
    any unrecognized value so the caller falls back to the legacy sender.
    """
    from app.channels import types as ct

    if channel in (
        ct.PROVIDER_ZALO_BOT,
        ct.PROVIDER_ZALO_OA,
        ct.PROVIDER_FACEBOOK_MESSENGER,
    ):
        return channel
    return None
