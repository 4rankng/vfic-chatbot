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
        ts_header = request.headers.get("x-zevent-timestamp") or ""
        body_ts = str(
            payload.get("timestamp") or payload.get("timeStamp") or payload.get("time_stamp") or ""
        )
        if not _verify_oa_signature(
            signature=signature,
            raw=raw,
            payload=payload,
            app_id=cfg.oa_app_id,
            secret_key=cfg.oa_secret_key,
            timestamp_header=ts_header,
        ):
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
                "zalo oa signature mismatch secret_len=%d ts=%r recv_sig=%r "
                "candidates=%s matched=%s body=%r",
                len(cfg.oa_secret_key),
                body_ts,
                recv,
                _cands,
                _match,
                _body,
            )
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
    timestamp_header: str = "",
) -> bool:
    """Verify Zalo OA webhook signature.

    Zalo signs sha256(appId + data + timeStamp + OAsecretKey): ``data`` is the
    raw request body (or a nested ``data`` field serialized as JSON) and
    ``timeStamp`` is the value of the X-ZEvent-Timestamp HEADER. Reading the
    body field instead of the header is the classic cause of a permanent 401 —
    the two need not be equal. The header may arrive bare or as
    ``sha256=<hex>``/``mac=<hex>``.
    """
    if not signature or not app_id or not secret_key:
        return False
    normalized = signature.strip()
    for prefix in ("sha256=", "mac="):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    # Zalo signs sha256(appId + data + timeStamp + OAsecretKey). ``data`` is the
    # raw request body (normal events) or a nested ``data`` field serialized as
    # JSON (str() would emit Python repr with single quotes and never match).
    # ``timeStamp`` is the X-ZEvent-Timestamp HEADER; keep the body field as a
    # fallback for variants that put it only in the payload, then try every
    # (data, ts) combination so a genuine signature matches regardless of form.
    ts_candidates: list[str] = []
    if timestamp_header:
        ts_candidates.append(str(timestamp_header))
    body_ts = payload.get("timestamp") or payload.get("timeStamp") or payload.get("time_stamp")
    if body_ts:
        ts_candidates.append(str(body_ts))
    if not ts_candidates:
        ts_candidates.append("")

    data_candidates: list[str] = [raw.decode("utf-8", "replace")]
    data = payload.get("data")
    if data is not None:
        data_candidates.append(_to_json(data))
    data_candidates.append(_to_json(payload))

    for ts in ts_candidates:
        for data_text in data_candidates:
            digest = hashlib.sha256(
                f"{app_id}{data_text}{ts}{secret_key}".encode("utf-8")
            ).hexdigest()
            if hmac.compare_digest(normalized, digest):
                return True
    return False


def _to_json(value: object) -> str:
    """Serialize ``value`` as Zalo's JSON.stringify would: compact separators,
    non-ASCII kept literal, insertion order preserved (Python dicts are ordered)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
