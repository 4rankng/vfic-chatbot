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
        return JSONResponse({"detail": "webhook verification not configured"}, status_code=503)
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

    # Zalo verifies a newly configured OA webhook URL with an unsigned POST whose
    # body is an empty JSON object. It must receive 200 before Zalo will save the
    # URL. Accept only that side-effect-free probe; every real event below still
    # requires X-ZEvent-Signature verification.
    if payload == {} and not request.headers.get("x-zevent-signature"):
        return JSONResponse({"status": "verified"}, status_code=200)

    cfg = await IntegrationSettingsService(db).resolve_zalo()
    if cfg.oa_secret_key:
        signature = request.headers.get("x-zevent-signature") or ""
        ts_header = request.headers.get("x-zevent-timestamp") or ""
        signed_app_id = str(payload.get("app_id") or cfg.oa_app_id or "")
        body_ts = str(
            payload.get("timestamp") or payload.get("timeStamp") or payload.get("time_stamp") or ""
        )
        oa_result = verify_signature(
            signature=signature,
            raw=raw,
            payload=payload,
            app_id=signed_app_id,
            secret_key=cfg.oa_secret_key,
            timestamp_header=ts_header,
        )
        if oa_result.verified:
            asyncio.create_task(record_oa_signature(ok=True))
        else:
            # NOTE: signature verification is currently NON-BLOCKING. A mismatch is
            # recorded to the passive health badge (so admins see a wrong/stale OA
            # secret in the integration status) and logged, but the event is still
            # processed. Blocking was enabled in 156202f7 but had to be reverted:
            # while the stored OA secret disagrees with Zalo's signing, EVERY real
            # event — including ``user_seen_message`` receipts and inbound text — is
            # rejected with 401, which Zalo surfaces as "Không thể kết nối với
            # webhook" and silently drops the event. Re-enable the hard reject once
            # the OA secret is confirmed correct (health badge stays "verified").
            logger.warning(
                "zalo oa signature mismatch (non-blocking) app_id=%r event_name=%r "
                "payload_keys=%r ts_header=%r body_ts=%r sig=%r",
                signed_app_id,
                str(payload.get("event_name") or ""),
                sorted(str(key) for key in payload),
                ts_header,
                body_ts,
                signature,
            )
            asyncio.create_task(record_oa_signature(ok=False))
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
