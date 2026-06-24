"""POST /webhooks/zalo — Zalo OA inbound. Acks synchronously (<1s) after the
guard chain; the bot run is enqueued to RQ.

When a Zalo OA verification secret is configured (zalo_oa_secret), inbound
requests are HMAC-verified against the X-Zevent-Signature header. With no secret
(dev/test), verification is skipped and the webhook is accepted unchanged.
"""
import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.services.webhook import ZaloWebhookService
from app.workers.chatbot_worker import enqueue_chat_run

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
_settings = get_settings()


def _verify_signature(raw: bytes, header: str | None) -> bool:
    """Zalo OA event webhook signs the raw body: X-Zevent-Signature: mac=<hex>,
    where hex = HMAC-SHA256(oa_secret, raw_body). Constant-time compared."""
    expected = "mac=" + hmac.new(
        _settings.zalo_oa_secret.encode(), raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(header or "", expected)


@router.post("/zalo")
async def zalo_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    # Read the RAW body so signature verification matches the exact bytes Zalo
    # signed (a re-serialized JSON object would not match).
    raw = await request.body()
    if _settings.zalo_oa_secret and not _verify_signature(
        raw, request.headers.get("x-zevent-signature")
    ):
        return JSONResponse({"detail": "invalid signature"}, status_code=401)
    payload = json.loads(raw)
    result = await ZaloWebhookService.handle(db, payload, enqueue=enqueue_chat_run)
    return JSONResponse(result, status_code=200)
