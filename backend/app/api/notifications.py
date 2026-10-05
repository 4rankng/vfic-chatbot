"""Web Push subscription API for the console's notification bell.

The console subscribes with the deployment's VAPID public key, then posts the
browser's subscription here. Alerts themselves are server-to-browser
(``app/services/push/service.py``); these routes only manage the handles, and
every ORM/config read lives behind that service so the API layer stays transport.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import get_current_user
from app.identity.application.http import AuthenticatedUser
from app.schemas.notifications import (
    PushTestOut,
    SubscriptionIn,
    SubscriptionOut,
    VapidKeyOut,
)
from app.services.push import (
    delete_subscription,
    push_enabled,
    save_subscription,
    send_to_users,
    user_subscription_count,
    vapid_public_key,
)
from app.shared.infrastructure.db import get_request_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/vapid-public-key", response_model=VapidKeyOut)
async def get_vapid_public_key(
    _user: AuthenticatedUser = Depends(get_current_user),
) -> VapidKeyOut:
    """The application server key the browser must subscribe with.

    Public by design: it is the key half that identifies the deployment to the
    push service, and the browser cannot subscribe without it. ``enabled`` is
    false when the deployment has no VAPID pair, and the console then hides the
    toggle instead of failing a subscribe attempt.
    """
    return VapidKeyOut(enabled=push_enabled(), key=vapid_public_key())


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    body: SubscriptionIn,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> None:
    """Store (or refresh) this browser's subscription for the caller."""
    await save_subscription(
        db,
        user_id=user.id,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        user_agent=body.user_agent,
    )


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    body: SubscriptionOut,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> None:
    """Forget this browser's subscription (the toggle was switched off)."""
    await delete_subscription(db, user_id=user.id, endpoint=body.endpoint)


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
    if await user_subscription_count(db, user.id) == 0:
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
