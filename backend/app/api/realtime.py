"""SSE realtime: GET /realtime/events streams message.* / conversation.* events.

EventSource cannot set Authorization headers, so the JWT is accepted via ?token=
(or the Bearer header). Auth is enforced before the stream opens.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import get_user_from_token
from app.core.db import get_db
from app.core.redis import get_redis
from app.models.user import User
from app.services.realtime import CHANNEL

router = APIRouter()


async def _user_from_request(request: Request, db: AsyncSession) -> User:
    # Token can arrive as ?token= (EventSource can't set headers) or Bearer.
    token = request.query_params.get("token")
    if not token:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    return await get_user_from_token(token, db)


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
