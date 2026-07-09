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
import hashlib
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
            # Bring-up diagnostic: log received vs every plausible computed
            # digest so we can tell a wrong secret from a different signing
            # scheme. Remove once the OA webhook verifies.
            recv = signature.strip()
            for _p in ("sha256=", "mac="):
                if recv.startswith(_p):
                    recv = recv[len(_p):]
            _body = raw.decode("utf-8", "replace")
            _cands = {
                "sha256(app+body+ts+secret)": hashlib.sha256(
                    f"{cfg.oa_app_id}{_body}{body_ts}{cfg.oa_secret_key}".encode()
                ).hexdigest(),
                "hmac_sha256(secret,app+body+ts)": hmac.new(
                    cfg.oa_secret_key.encode(),
                    f"{cfg.oa_app_id}{_body}{body_ts}".encode(),
                    hashlib.sha256,
                ).hexdigest(),
                "hmac_sha256(secret,body)": hmac.new(
                    cfg.oa_secret_key.encode(), _body.encode(), hashlib.sha256
                ).hexdigest(),
                "sha256(body+secret)": hashlib.sha256(
                    f"{_body}{cfg.oa_secret_key}".encode()
                ).hexdigest(),
            }
            _match = [k for k, v in _cands.items() if hmac.compare_digest(recv, v)]
            logger.warning(
                "zalo oa webhook headers=%r raw_repr=%r",
                {k: v for k, v in request.headers.items()},
                raw,
            )
            logger.warning(
                "zalo oa signature mismatch secret_len=%d ts=%r recv_sig=%r "
                "candidates=%s matched=%s body=%r",
                len(cfg.oa_secret_key),
                body_ts,
                recv,
                _cands,
                _match,
                _body,
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
    code = 503 if result.get("status") == "enqueue_failed" else 200
    return JSONResponse(result, status_code=code)
