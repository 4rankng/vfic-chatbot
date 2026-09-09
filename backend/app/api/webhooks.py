"""POST /webhooks/zalo/chatbot — Zalo Bot Platform inbound. Acks synchronously (<1s)
after the guard chain; the bot run is enqueued to RQ.

Inbound authenticity is verified via the X-Bot-Api-Secret-Token shared secret
echoed by Zalo on every POST (the value passed to setWebhook as ``secret_token``).
Outside development, a request with NO secret configured is rejected (503) rather
than accepted blind — an unauthenticated inbound endpoint would let anyone inject
messages that trigger bot turns + lead extraction. Dev/test keeps the
accept-unsigned behavior for ergonomics.

Only request size and safe event metadata are logged. Candidate content, provider
signatures, timestamps, and identifiers never enter application logs.
"""

import hmac
import json
import logging
import time

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.composition.conversation_messaging import (
    enqueue_chat_turn,
    run_zalo_ingress,
    webhook_app_env,
)
from app.conversation_messaging.infrastructure.webhook_delivery import (
    apply_messenger_receipt,
    enqueue_facebook_turn,
)
from app.shared.infrastructure.db import get_request_db
from app.services.integration_settings import IntegrationSettingsService
from app.services.installation.service import InstallationService
from app.services.slo_service import record_webhook_ack_ms

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])
_APP_ENV = webhook_app_env()


async def _stamp_ack(t0: float, status_code: int) -> None:
    """Sample webhook-ack latency into the SLO sliding window (best-effort).

    Only samples successful (2xx) acks — 4xx/5xx are rejection paths with
    different latency characteristics and would skew the SLO.
    """
    if 200 <= status_code < 300:
        await record_webhook_ack_ms((time.time() - t0) * 1000.0)


async def _runtime_authority_or_inactive(db: AsyncSession, *, channel: str):
    """Resolve active authority after signature verification and before any business write."""
    active = await InstallationService(db).resolve_active()
    if active is None:
        logger.info("webhook accepted while runtime inactive channel=%s", channel)
        return None
    return active.fingerprint.stamp()


@router.post("/zalo/chatbot")
async def zalo_webhook(
    request: Request, db: AsyncSession = Depends(get_request_db)
) -> JSONResponse:
    t0 = time.time()  # webhook_ack SLO (Directive §1) — sampled on success
    # Read the raw body once for JSON parsing and signature verification.
    raw = await request.body()
    logger.info("zalo webhook inbound bytes=%d", len(raw))

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await _stamp_ack(t0, 400)
        return JSONResponse({"detail": "invalid JSON body"}, status_code=400)

    cfg = await IntegrationSettingsService(db).resolve_zalo()
    bot_secret = cfg.bot_webhook_secret
    if bot_secret:
        # Bot Platform: shared-secret echo (X-Bot-Api-Secret-Token).
        token = request.headers.get("x-bot-api-secret-token") or ""
        if not hmac.compare_digest(token, bot_secret):
            await _stamp_ack(t0, 401)
            return JSONResponse({"detail": "invalid secret token"}, status_code=401)
    elif _APP_ENV != "development":
        # No secret configured in non-dev -> refuse rather than accept blind.
        await _stamp_ack(t0, 503)
        return JSONResponse({"detail": "webhook verification not configured"}, status_code=503)
    # else: dev/test with no secret -> accept unchanged (ergonomics).

    # Pass the DB-resolved bot token so the fire-and-forget typing indicator uses
    # the live token (the env ZALO_BOT_TOKEN is stale; resolve_zalo wins).
    runtime_authority = await _runtime_authority_or_inactive(db, channel="bot")
    result = await run_zalo_ingress(
        db,
        payload,
        enqueue=enqueue_chat_turn,
        bot_token=cfg.bot_token,
        runtime_authority=runtime_authority,
    )
    code = 503 if result.get("status") == "start_failed" else 200
    await _stamp_ack(t0, code)
    return JSONResponse(result, status_code=code)


@router.post("/zalo/oa")
async def zalo_oa_webhook(
    request: Request, db: AsyncSession = Depends(get_request_db)
) -> JSONResponse:
    t0 = time.time()  # webhook_ack SLO (Directive §1) — sampled on success
    raw = await request.body()
    logger.info("zalo oa webhook inbound bytes=%d", len(raw))

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await _stamp_ack(t0, 400)
        return JSONResponse({"detail": "invalid JSON body"}, status_code=400)

    # Zalo verifies a newly configured OA webhook URL with an unsigned POST whose
    # body is an empty JSON object. It must receive 200 before Zalo will save the
    # URL. Accept only that side-effect-free probe; real events below are processed
    # WITHOUT X-ZEvent-Signature verification (see the retirement note below).
    if payload == {} and not request.headers.get("x-zevent-signature"):
        await _stamp_ack(t0, 200)
        return JSONResponse({"status": "verified"}, status_code=200)

    # Inbound OA signature verification is intentionally non-enforced: the held
    # ``oa_secret_key`` is the OA access-token secret, not Zalo's webhook signing
    # key, so the check false-rejected 100% of real events while being non-blocking
    # (zero protection). The manual admin verify probe
    # (POST /zalo/oa/verify-signature) remains as a diagnostic for a future
    # cutover when a dedicated signing secret is available.

    runtime_authority = await _runtime_authority_or_inactive(db, channel="oa")
    result = await run_zalo_ingress(
        db,
        payload,
        enqueue=enqueue_chat_turn,
        channel="oa",
        runtime_authority=runtime_authority,
    )
    code = 503 if result.get("status") == "start_failed" else 200
    await _stamp_ack(t0, code)
    return JSONResponse(result, status_code=code)


# ─── Facebook Messenger webhook (Phase 5) ───────────────────────────────────
#
# Two routes, additive to the Zalo routes above. The shared helpers
# (_stamp_ack, _runtime_authority_or_inactive) are reused. The body is NEVER
# logged (it can carry candidate text); only bytes=N is logged, matching the
# Zalo pattern. Signature verification runs over the RAW body before any JSON
# parse or business write — re-serializing JSON breaks the HMAC.


async def _resolve_active_facebook_page(db: AsyncSession):
    """Return (FacebookRuntimeConfig, ChannelAccountRef) for the active Page, or (None, None)."""
    from app.channels.providers.facebook_account import FacebookAccountResolver
    from app.services.integration_settings import IntegrationSettingsService

    resolver = FacebookAccountResolver(db)
    active = await resolver.active_facebook_page()
    if active is None or not active.is_active:
        return None, None
    settings_service = IntegrationSettingsService(db)
    cfg = await settings_service.resolve_facebook(active.account_key)
    return cfg, active


@router.get("/facebook")
async def facebook_webhook_verify(
    request: Request, db: AsyncSession = Depends(get_request_db)
) -> Response:
    """GET challenge — Meta subscribes a webhook URL by sending
    ``hub.mode=subscribe`` + ``hub.verify_token`` + ``hub.challenge``.

    Constant-time compare against ``meta_webhook_verify_token``; respond with
    the challenge only on exact match. No DB mutation. A missing configured
    verify token in non-dev refuses (503) rather than accepting blind.
    """
    from app.channels.providers.facebook_signature import constant_time_verify_token

    mode = request.query_params.get("hub.mode") or ""
    sent_token = request.query_params.get("hub.verify_token") or ""
    challenge = request.query_params.get("hub.challenge") or ""
    # Resolve verify_token DB-first (env fallback) so an admin who rotates it
    # via the UI does not have to redeploy for Meta's re-subscribe challenge.
    oauth_cfg = await IntegrationSettingsService(db).resolve_facebook_oauth()
    expected = oauth_cfg.verify_token
    if not expected and _APP_ENV != "development":
        return JSONResponse(
            {"detail": "webhook verification not configured"}, status_code=503
        )
    if mode == "subscribe" and constant_time_verify_token(sent=sent_token, expected=expected):
        return PlainTextResponse(challenge, status_code=200)
    return JSONResponse({"detail": "verification failed"}, status_code=403)


@router.post("/facebook")
async def facebook_webhook(
    request: Request, db: AsyncSession = Depends(get_request_db)
) -> JSONResponse:
    """POST event — verify the X-Hub-Signature-256 over the RAW body, then
    normalize text events and apply receipts.

    Invalid/missing signature → 200 ack with NO side effects. Meta retries on
    non-2xx, so rejecting with 4xx would cause a retry loop for any malformed/
    replayed request; ack-and-drop is the documented pattern. The body is never
    logged (it can contain candidate text).
    """
    from app.channels.providers.facebook_messenger import FacebookMessengerNormalizer
    from app.channels.providers.facebook_signature import verify_messenger_signature

    t0 = time.time()
    raw = await request.body()
    logger.info("facebook webhook inbound bytes=%d", len(raw))

    # 1. Signature verification over RAW bytes BEFORE any JSON parse / write.
    # Resolve app_secret DB-first (env fallback) so an admin who rotates it via
    # the UI takes effect on the next inbound without a redeploy.
    oauth_cfg = await IntegrationSettingsService(db).resolve_facebook_oauth()
    app_secret = oauth_cfg.app_secret
    sig_header = request.headers.get("x-hub-signature-256") or ""
    verification = verify_messenger_signature(
        signature_header=sig_header, raw_body=raw, app_secret=app_secret
    )
    if not verification.verified:
        # Ack-and-drop: no business write, no log of the body.
        logger.info("facebook webhook signature rejected reason=%s", verification.reason)
        await _stamp_ack(t0, 200)
        return JSONResponse({"status": "ignored"}, status_code=200)

    # 2. Parse the authenticated body.
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await _stamp_ack(t0, 200)
        return JSONResponse({"status": "ignored"}, status_code=200)

    # 3. Resolve the connected Page. An inactive/missing Page acks events as
    #    inactive (no message/bot turn) so a disconnected Page's traffic is
    #    safely absorbed rather than dropping with an error.
    cfg, active = await _resolve_active_facebook_page(db)
    if cfg is None:
        logger.info("facebook webhook accepted with no active Page")
        await _stamp_ack(t0, 200)
        return JSONResponse({"status": "inactive"}, status_code=200)

    # 4. Normalize + dispatch receipts first (delivery/read), then text events.
    normalizer = FacebookMessengerNormalizer()
    messages, ignored = normalizer.normalize(payload)
    receipt = normalizer.parse_receipt_from_payload(payload)
    if receipt is not None:
        try:
            await apply_messenger_receipt(db, receipt, active.account_key)
        except Exception:  # noqa: BLE001 — receipts are best-effort; never fail the ack
            logger.info("facebook receipt apply failed account_suffix=%s", active.account_key[-4:])

    if ignored:
        logger.info("facebook webhook ignored events reasons=%s", dict(ignored))

    # 5. Feed each text event to the shared ingress pipeline.
    from app.channels.ingress import ChannelIngressService

    ingress = ChannelIngressService(db)
    runtime_authority = await _runtime_authority_or_inactive(db, channel="facebook")
    for msg in messages:
        # Page id in the payload must match the connected active Page; a
        # mismatched event is acknowledged and ignored (no cross-Page leak).
        if msg.identity.account_key != active.account_key:
            logger.info(
                "facebook webhook event page mismatch (dropped) event_page_suffix=%s",
                msg.identity.account_key[-4:],
            )
            continue
        try:
            outcome = await ingress.ingest(msg)
        except Exception as exc:  # noqa: BLE001 — one event must not fail the batch
            # Log the cause, not just the fact: without it a broken ingress is
            # indistinguishable from a quiet drop. The message body is still
            # never logged (it can contain candidate text).
            logger.warning(
                "facebook ingress ingest failed: error=%s: %s",
                type(exc).__name__,
                exc,
            )
            continue
        if outcome.status != "persisted":
            continue
        # Enqueue a bot turn for the persisted message, mirroring the Zalo
        # webhook flow. The v2 job payload carries only neutral ids.
        try:
            await enqueue_facebook_turn(
                db,
                outcome,
                runtime_authority,
                enqueue=enqueue_chat_turn,
            )
        except Exception:  # noqa: BLE001 — enqueue failure is recovered by reconcile
            logger.info("facebook turn enqueue failed conversation=%s", outcome.conversation_id)

    await _stamp_ack(t0, 200)
    return JSONResponse({"status": "processed"}, status_code=200)
