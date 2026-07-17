"""Channel-neutral ingress service (Phase 3).

Owns the shared dedup → ensure → persist → enqueue pipeline that the Zalo
webhook handler (and, in Phase 5, the Messenger webhook handler) feed. The
provider edge owns signature verification and payload → :class:`ChannelInboundMessage`
normalization; this service owns everything from there.

Dedup key is ``(provider, account_key, external_id, external_message_id)`` —
the durable idempotency boundary. The transient ``message_dedup`` table (8s
window) remains a short-term optimization for high-frequency duplicate webhooks;
the Phase 2 ``messages(conversation_id, provider_message_id)`` partial unique
index is the final authority (so a duplicate that survives the 8s window is
still suppressed at persist time).

Phase 3 ships this as an additive layer. The existing :func:`ZaloWebhookService.handle`
keeps working; it migrates to call this service as part of the wiring step.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.channels import types as ct

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def neutral_dedup_key(msg: ct.ChannelInboundMessage) -> str:
    """The deterministic dedup key for a neutral inbound message.

    Scoped by (provider, account_key, external_id, external_message_id) so the
    same PSID on two Pages, or the same chat id on Bot vs OA, never collide.
    """
    raw = (
        f"{msg.identity.provider}:{msg.identity.account_key}:"
        f"{msg.identity.external_id}:{msg.external_message_id}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class IngressOutcome:
    """The durable outcome of one inbound event.

    ``persisted`` means a new message row was written and the caller may enqueue
    a bot turn. ``duplicate`` means the (provider, account, message) triple was
    already processed. ``ignored`` means the event was acknowledged without
    persistence (non-text, or an inactive account scope).
    """

    status: Literal["persisted", "duplicate", "ignored"]
    conversation_id: str | None = None
    dedup_key: str | None = None


class ChannelIngressService:
    """Shared dedup → ensure → persist pipeline for one inbound text.

    The service is constructed per-webhook-call. It does NOT own enqueueing —
    the caller decides whether to enqueue a bot turn based on the outcome and
    the conversation's mode/lock state. Keeping enqueue out of this service
    preserves the existing webhook's guard chain (run_start_guard, acquire_lock,
    human-mode starvation) which is Zalo-equivalent but not ingress-owned.
    """

    def __init__(self, db: "AsyncSession") -> None:
        self.db = db

    async def ingest(
        self,
        msg: ct.ChannelInboundMessage,
    ) -> IngressOutcome:
        """Persist one inbound text under the neutral contract.

        Steps:
        1. Dedup via the transient ``message_dedup`` table (short-window guard).
        2. Ensure Contact + identity + conversation via ``ensure_by_identity``.
        3. Persist the candidate message (carries the neutral provider_message_id,
           which the partial unique index enforces as the final idempotency
           boundary).
        4. Return the outcome so the caller can enqueue/guard as appropriate.

        The caller is responsible for authenticity verification and payload →
        :class:`ChannelInboundMessage` normalization. This service never sees a
        raw provider payload.
        """
        from app.services.conversation import ConversationService
        from app.services.dedup import MessageDedupService

        dedup_key = neutral_dedup_key(msg)

        # 1. Short-window dedup guard. The DB unique constraint on
        # (conversation_id, provider_message_id) is the final authority; this
        # transient claim is an optimization for high-frequency duplicate webhooks.
        if not await MessageDedupService.claim(
            self.db,
            f"{msg.identity.provider}:{msg.identity.account_key}:{msg.identity.external_id}",
            dedup_key,
        ):
            return IngressOutcome(status="duplicate", dedup_key=dedup_key)

        svc = ConversationService(self.db)
        conv = await svc.ensure_by_identity(
            provider=msg.identity.provider,
            account_key=msg.identity.account_key,
            external_id=msg.identity.external_id,
            zalo_chat_id_alias=None,
            zalo_channel_alias="bot",
        )
        await self.db.refresh(conv)

        # 2. Persist the candidate message under the neutral id. The unique
        # index on (conversation_id, provider_message_id) suppresses a duplicate
        # that survived the transient window.
        try:
            await svc.record_inbound(
                conv,
                body=msg.text,
                provider_message_id=msg.external_message_id,
                runtime_revision_id=None,
                authority_generation=None,
                runtime_fingerprint=None,
            )
        except Exception:
            # A duplicate-message unique-violation here means the transient
            # dedup let a late-arriving duplicate through. Roll back the claim
            # and report duplicate so the caller acks without a turn.
            await self.db.rollback()
            return IngressOutcome(status="duplicate", dedup_key=dedup_key)

        return IngressOutcome(
            status="persisted",
            conversation_id=str(conv.id),
            dedup_key=dedup_key,
        )


__all__ = ["ChannelIngressService", "IngressOutcome", "neutral_dedup_key"]
