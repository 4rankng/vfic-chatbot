"""Web Push fan-out for the two conditions nobody is watching for.

Both alerts exist because the failure is silent by nature: an OA whose refresh
token died keeps serving nothing while the console looks idle, and a reply the
provider refuses is only visible if someone opens that thread. The push reaches
the operator's browser instead (the service worker in
``frontend/public/push-sw.js``).

Best-effort by contract: every entry point swallows its own failures. A dead push
service must never turn an inbound turn, a reconcile sweep, or a token refresh
into an error.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.models.push_subscription import PushSubscription
from app.models.user import Role, User

logger = logging.getLogger(__name__)

# A push service answering 404/410 means the browser is gone (uninstalled, or a
# newer subscription replaced it). Anything else is transient.
_GONE_STATUS = (404, 410)

# Below this, a re-notify for the same condition is noise: a dead OA token or an
# undeliverable thread stays broken until an operator acts, and the trigger sites
# run every minute.
DEFAULT_DEDUPE_SECONDS = 6 * 3600


@dataclass(frozen=True, slots=True)
class PushTarget:
    """One endpoint, flattened out of the ORM so the send thread owns no session."""

    id: uuid.UUID
    endpoint: str
    p256dh: str
    auth: str


def push_enabled() -> bool:
    """Whether the VAPID pair is configured (blank keys disable the channel)."""
    settings = get_settings()
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def vapid_public_key() -> str:
    """The application server key browsers must subscribe with (public by design)."""
    return get_settings().vapid_public_key


async def save_subscription(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
) -> None:
    """Store (or refresh) one browser's subscription for a user.

    Upsert on ``endpoint``: the same browser re-subscribing rotates its keys, and
    a device that switched accounts must move to the new owner rather than leave a
    row pointing at the previous user. Lives here (not in the router) so the API
    layer never touches the ORM — the architecture gate rejects that edge.
    """
    statement = pg_insert(PushSubscription).values(
        user_id=user_id,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=user_agent,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[PushSubscription.endpoint],
            set_={
                "user_id": statement.excluded.user_id,
                "p256dh": statement.excluded.p256dh,
                "auth": statement.excluded.auth,
                "user_agent": statement.excluded.user_agent,
                "failure_count": 0,
            },
        )
    )
    await db.commit()


async def delete_subscription(db: AsyncSession, *, user_id: uuid.UUID, endpoint: str) -> None:
    """Forget one browser's subscription. Scoped to the caller: an endpoint that
    belongs to another user is not theirs to delete, and the browser unsubscribes
    locally either way."""
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == endpoint,
            PushSubscription.user_id == user_id,
        )
    )
    await db.commit()


async def user_subscription_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """How many browsers this user has registered (the self-test's precondition)."""
    ids = await db.scalars(
        select(PushSubscription.id).where(PushSubscription.user_id == user_id)
    )
    return len(list(ids))


async def alert_once(dedupe_key: str, *, ttl_seconds: int = DEFAULT_DEDUPE_SECONDS) -> bool:
    """True when this condition has not been alerted within ``ttl_seconds``.

    Redis SET NX is the lock: the trigger runs on several workers, and without it
    a dead OA token would push a notification on every tick of every replica.
    A Redis failure fails OPEN (returns True) — an extra notification beats a
    silent outage.
    """
    try:
        acquired = await get_redis().set(
            f"push:dedupe:{dedupe_key}", "1", nx=True, ex=ttl_seconds
        )
    except Exception:  # noqa: BLE001 — dedupe must never block the alert
        logger.warning("push dedupe unavailable for key=%s; notifying", dedupe_key)
        return True
    return bool(acquired)


def _send_sync(targets: list[PushTarget], payload: dict) -> list[uuid.UUID]:
    """Deliver to each endpoint in this thread; return the ones the browser dropped."""
    from pywebpush import WebPushException, webpush

    settings = get_settings()
    gone: list[uuid.UUID] = []
    body = json.dumps(payload, ensure_ascii=False)
    for target in targets:
        try:
            webpush(
                subscription_info={
                    "endpoint": target.endpoint,
                    "keys": {"p256dh": target.p256dh, "auth": target.auth},
                },
                data=body,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
                timeout=10,
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in _GONE_STATUS:
                gone.append(target.id)
            else:
                logger.warning(
                    "push delivery failed endpoint_id=%s status=%s", target.id, status
                )
        except Exception:  # noqa: BLE001 — one bad endpoint must not stop the rest
            logger.warning("push delivery error endpoint_id=%s", target.id, exc_info=True)
    return gone


async def send_to_users(db: AsyncSession, user_ids: list[uuid.UUID], payload: dict) -> int:
    """Push ``payload`` to every subscription of ``user_ids``; return the count sent.

    ``pywebpush`` is synchronous (requests + ECDH), so it runs in a worker thread
    — the caller may be a request handler or the reconcile sweep.
    """
    if not push_enabled() or not user_ids:
        return 0
    rows = (
        await db.execute(
            select(
                PushSubscription.id,
                PushSubscription.endpoint,
                PushSubscription.p256dh,
                PushSubscription.auth,
            ).where(PushSubscription.user_id.in_(user_ids))
        )
    ).all()
    targets = [PushTarget(*row) for row in rows]
    if not targets:
        return 0
    gone = await asyncio.to_thread(_send_sync, targets, payload)
    gone_ids = set(gone)
    if gone:
        await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone_ids)))
    live = [target.id for target in targets if target.id not in gone_ids]
    if live:
        await db.execute(
            update(PushSubscription)
            .where(PushSubscription.id.in_(live))
            .values(last_seen_at=datetime.now(timezone.utc))
        )
    await db.commit()
    return len(live)


async def notify_admins(
    db: AsyncSession,
    *,
    title: str,
    body: str,
    url: str,
    tag: str,
    dedupe_key: str,
    ttl_seconds: int = DEFAULT_DEDUPE_SECONDS,
) -> int:
    """Alert every active admin once per ``dedupe_key`` window.

    Admins are the audience the console's ops surfaces already target, and the
    failures these alerts describe are theirs to fix (re-authorize a channel,
    open the stuck thread).
    """
    if not push_enabled():
        logger.info("push disabled (no VAPID keys); alert dropped tag=%s", tag)
        return 0
    if not await alert_once(dedupe_key, ttl_seconds=ttl_seconds):
        return 0
    admin_ids = list(
        await db.scalars(
            select(User.id).where(User.role == Role.admin, User.disabled.is_(False))
        )
    )
    sent = await send_to_users(db, admin_ids, {"title": title, "body": body, "url": url, "tag": tag})
    logger.info("push alert sent=%d tag=%s", sent, tag)
    return sent
