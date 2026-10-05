"""Web Push subscription API for the console's notification bell.

The console subscribes with the deployment's VAPID public key, then posts the
browser's subscription here. Alerts themselves are server-to-browser
(``app/services/push/service.py``); these routes only manage the handles.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import get_current_user
from app.core.config import get_settings
from app.identity.application.http import AuthenticatedUser
from app.models.push_subscription import PushSubscription
from app.services.push import push_enabled, send_to_users
from app.shared.infrastructure.db import get_request_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2000)
    keys: SubscriptionKeys
    user_agent: str | None = Field(default=None, max_length=300)


class SubscriptionOut(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2000)


class VapidKeyOut(BaseModel):
    enabled: bool
    key: str


class PushTestOut(BaseModel):
    sent: int


@router.get("/vapid-public-key", response_model=VapidKeyOut)
async def vapid_public_key(
    _user: AuthenticatedUser = Depends(get_current_user),
) -> VapidKeyOut:
    """The application server key the browser must subscribe with.

    Public by design: it is the key half that identifies the deployment to the
    push service, and the browser cannot subscribe without it. ``enabled`` is
    false when the deployment has no VAPID pair, and the console then hides the
    toggle instead of failing a subscribe attempt.
    """
    return VapidKeyOut(enabled=push_enabled(), key=get_settings().vapid_public_key)


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    body: SubscriptionIn,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> None:
    """Store (or refresh) this browser's subscription for the caller.

    Upsert on ``endpoint``: the same browser re-subscribing rotates its keys, and
    a device that switched accounts must move to the new owner rather than leave
    a row pointing at the previous user.
    """
    statement = pg_insert(PushSubscription).values(
        user_id=user.id,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        user_agent=body.user_agent,
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


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    body: SubscriptionOut,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> None:
    """Forget this browser's subscription (the toggle was switched off).

    Scoped to the caller: an endpoint belonging to another user is not theirs to
    delete, and the browser unsubscribes locally either way.
    """
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint,
            PushSubscription.user_id == user.id,
        )
    )
    await db.commit()


@router.post("/test", response_model=PushTestOut)
async def send_test(
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> PushTestOut:
    """Send one push to the caller's own subscriptions.

    Exists so the toggle can prove itself: a browser that stored a subscription
    but never receives (blocked permission, a stale VAPID pair) is otherwise
    indistinguishable from a deployment with nothing to alert about.
    """
    if not push_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Thông báo đẩy chưa được cấu hình trên máy chủ.",
        )
    handlers = list(
        await db.scalars(select(PushSubscription.id).where(PushSubscription.user_id == user.id))
    )
    if not handlers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Trình duyệt này chưa đăng ký nhận thông báo đẩy.",
        )
    return PushTestOut(
        sent=await send_to_users(
            db,
            [user.id],
            {
                "title": "TingTing",
                "body": "Thông báo đẩy đã hoạt động.",
                "url": "/",
                "tag": "push-test",
            },
        )
    )
