"""SSE realtime: GET /realtime/events streams message.* / conversation.* events.

EventSource cannot set Authorization headers, so the JWT is accepted via ?token=
(or the Bearer header). Auth is enforced before the stream opens.
"""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.db import get_db
from app.core.redis import get_redis
from app.core.security import decode_token
from app.models.user import User
from app.services.realtime import CHANNEL

router = APIRouter()


async def _user_from_request(request: Request, db: AsyncSession) -> User:
    token = request.query_params.get("token")
    if not token:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    try:
        payload = await decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
        uid = uuid.UUID(payload["sub"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc
    user = await db.get(User, uid)
    if user is None or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    # Reject access tokens superseded by a password change (ver mismatch).
    if payload.get("ver", 0) != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    return user


async def _event_generator(request: Request):
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        while True:
            if await request.is_disconnected():
                break
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg.get("type") == "message":
                data = json.loads(msg["data"])
                yield {"event": data["type"], "data": json.dumps(data["payload"])}
    finally:
        try:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()
        except Exception:  # noqa: BLE001 — SSE teardown must never raise
            pass


@router.get("/events")
async def events(request: Request, db: AsyncSession = Depends(get_db)) -> EventSourceResponse:
    await _user_from_request(request, db)
    return EventSourceResponse(_event_generator(request))
