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
import asyncio
import hmac
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.services.integration_settings import IntegrationSettingsService
from app.services.webhook import ZaloWebhookService
from app.services.zalo_oa_health import record_oa_signature
from app.services.zalo_oa_signature import verify_signature
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

    # Pass the DB-resolved bot token so the fire-and-forget typing indicator uses
    # the live token (the env ZALO_BOT_TOKEN is stale; resolve_zalo wins).
    result = await ZaloWebhookService.handle(
        db, payload, enqueue=enqueue_chat_run, bot_token=cfg.bot_token
    )
    code = 503 if result.get("status") == "start_failed" else 200
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
        ts_header = request.headers.get("x-zevent-timestamp") or ""
        body_ts = str(
            payload.get("timestamp") or payload.get("timeStamp") or payload.get("time_stamp") or ""
        )
        oa_result = verify_signature(
            signature=signature,
            raw=raw,
            payload=payload,
            app_id=cfg.oa_app_id,
            secret_key=cfg.oa_secret_key,
            timestamp_header=ts_header,
        )
        if not oa_result.verified:
            # The signing scheme is known (sha256(app_id+raw_body+header_ts+secret),
            # verified by app.services.zalo_oa_signature). A mismatch now means a
            # wrong/stale secret or a replay out of the timestamp window — log the
            # identifying headers (never the body/secret) and let the health badge
            # surface ongoing failures.
            logger.warning(
                "zalo oa signature mismatch app_id=%r ts_header=%r body_ts=%r sig=%r",
                cfg.oa_app_id,
                ts_header,
                body_ts,
                signature,
            )
            # Fire-and-forget: signature telemetry must never block the webhook
            # response or change the verdict (the recorder swallows its own errors).
            asyncio.create_task(record_oa_signature(ok=False))
            return JSONResponse({"detail": "invalid OA signature"}, status_code=401)
        asyncio.create_task(record_oa_signature(ok=True))
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
    code = 503 if result.get("status") == "start_failed" else 200
    return JSONResponse(result, status_code=code)
