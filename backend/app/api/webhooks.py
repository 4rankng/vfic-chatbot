"""POST /webhooks/zalo/chatbot — Zalo Bot Platform inbound. Acks synchronously (<1s)
after the guard chain; the bot run is enqueued to RQ.

Inbound authenticity is verified via the X-Bot-Api-Secret-Token shared secret
echoed by Zalo on every POST (the value passed to setWebhook as ``secret_token``).
Outside development, a request with NO secret configured is rejected (503) rather
than accepted blind — an unauthenticated inbound endpoint would let anyone inject
messages that trigger bot turns + lead extraction. Dev/test keeps the
accept-unsigned behavior for ergonomics.

The raw body is logged at INFO so the Bot Platform payload shape is observable
during bring-up.
"""
import hmac
import hashlib
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.services.integration_settings import IntegrationSettingsService
from app.services.webhook import ZaloWebhookService
from app.workers.chatbot_worker import enqueue_chat_run

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])
_settings = get_settings()


@router.post("/zalo/chatbot")
async def zalo_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    # Read the RAW body so logging shows the exact bytes Zalo sent.
    raw = await request.body()
    if _settings.app_env == "development":
        logger.info(
            "zalo webhook inbound bytes=%d body=%s",
            len(raw),
            raw.decode("utf-8", "replace")[:1000],
        )
    else:
        logger.info("zalo webhook inbound bytes=%d", len(raw))

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse({"detail": "invalid JSON body"}, status_code=400)

    cfg = await IntegrationSettingsService(db).resolve_zalo()
    bot_secret = cfg.bot_webhook_secret
    if bot_secret:
        # Bot Platform: shared-secret echo (X-Bot-Api-Secret-Token).
        token = request.headers.get("x-bot-api-secret-token") or ""
        if not hmac.compare_digest(token, bot_secret):
            return JSONResponse({"detail": "invalid secret token"}, status_code=401)
    elif _settings.app_env != "development":
        # No secret configured in non-dev -> refuse rather than accept blind.
        return JSONResponse(
            {"detail": "webhook verification not configured"}, status_code=503
        )
    # else: dev/test with no secret -> accept unchanged (ergonomics).

    result = await ZaloWebhookService.handle(db, payload, enqueue=enqueue_chat_run)
    code = 503 if result.get("status") == "enqueue_failed" else 200
    return JSONResponse(result, status_code=code)


@router.post("/zalo/oa")
async def zalo_oa_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    raw = await request.body()
    if _settings.app_env == "development":
        logger.info(
            "zalo oa webhook inbound bytes=%d body=%s",
            len(raw),
            raw.decode("utf-8", "replace")[:1000],
        )
    else:
        logger.info("zalo oa webhook inbound bytes=%d", len(raw))

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse({"detail": "invalid JSON body"}, status_code=400)

    cfg = await IntegrationSettingsService(db).resolve_zalo()
    if cfg.oa_secret_key:
        signature = request.headers.get("x-zevent-signature") or ""
        if not _verify_oa_signature(
            signature=signature,
            raw=raw,
            payload=payload,
            app_id=cfg.oa_app_id,
            secret_key=cfg.oa_secret_key,
        ):
            return JSONResponse({"detail": "invalid OA signature"}, status_code=401)
    elif _settings.app_env != "development":
        return JSONResponse(
            {"detail": "OA webhook verification not configured"},
            status_code=503,
        )

    result = await ZaloWebhookService.handle(
        db,
        payload,
        enqueue=enqueue_chat_run,
        channel="oa",
    )
    code = 503 if result.get("status") == "enqueue_failed" else 200
    return JSONResponse(result, status_code=code)


def _verify_oa_signature(
    *,
    signature: str,
    raw: bytes,
    payload: dict,
    app_id: str,
    secret_key: str,
) -> bool:
    """Verify Zalo OA webhook signature.

    Zalo documents X-ZEvent-Signature as sha256(appId + data + timestamp +
    OAsecretKey). The helper accepts the common bare hex form and
    ``sha256=<hex>``/``mac=<hex>`` variants.
    """
    if not signature or not app_id or not secret_key:
        return False
    normalized = signature.strip()
    for prefix in ("sha256=", "mac="):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    timestamp = str(
        payload.get("timestamp")
        or payload.get("timeStamp")
        or payload.get("time_stamp")
        or ""
    )
    data_candidates = [
        raw.decode("utf-8", "replace"),
    ]
    data = payload.get("data")
    if data is not None:
        data_candidates.append(str(data))
    for data_text in data_candidates:
        digest = hashlib.sha256(
            f"{app_id}{data_text}{timestamp}{secret_key}".encode("utf-8")
        ).hexdigest()
        if hmac.compare_digest(normalized, digest):
            return True
    return False
