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

Every webhook route is rate-limited per client IP (SEC-04) before the body is
read, and a body over ``MAX_WEBHOOK_BODY_BYTES`` is rejected with 413 — the
declared Content-Length is checked first so an oversized body is never buffered
(SEC-05).
"""

import hmac
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.composition.conversation_messaging import (
    enqueue_chat_turn,
    enqueue_chat_turn_async,
    enqueue_messenger_profile_enrichment,
    run_zalo_ingress,
    webhook_app_env,
)
from app.conversation_messaging.infrastructure.webhook_delivery import (
    apply_messenger_receipt,
    apply_messenger_referral,
    enqueue_facebook_turn,
    escalate_messenger_ad_entry,
)
from app.shared.infrastructure.db import get_request_db
from app.shared.infrastructure.rate_limits import enforce_webhook_rate_limit
from app.services.ingestion.limits import (
    MAX_WEBHOOK_BODY_BYTES,
    IngestionLimitError,
    assert_webhook_body_size,
)
from app.services.integration_settings import IntegrationSettingsService
from app.services.installation.service import InstallationService
from app.services.slo_service import record_webhook_ack_ms

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])
_APP_ENV = webhook_app_env()

_BODY_TOO_LARGE = "request body too large"


async def _stamp_ack(t0: float, status_code: int) -> None:
    """Sample webhook-ack latency into the SLO sliding window (best-effort).

    Only samples successful (2xx) acks — 4xx/5xx are rejection paths with
    different latency characteristics and would skew the SLO.
    """
    if 200 <= status_code < 300:
        await record_webhook_ack_ms((time.time() - t0) * 1000.0)


async def _read_body_within_limit(request: Request) -> bytes:
    """Read the raw body, rejecting anything over the webhook ceiling with 413.

    Content-Length is checked first so a declared-oversized body is rejected
    before the ASGI layer buffers it into memory; the post-read check catches a
    chunked body (no Content-Length) that only reveals its size while being read.
    Without this, an unauthenticated POST of any size was buffered whole (SEC-05).
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            too_large = int(declared) > MAX_WEBHOOK_BODY_BYTES
        except ValueError:
            too_large = False  # malformed header -> the server's own framing applies
        if too_large:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, _BODY_TOO_LARGE)
    raw = await request.body()
    try:
        assert_webhook_body_size(len(raw))
    except IngestionLimitError as exc:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, _BODY_TOO_LARGE
        ) from exc
    return raw


class _RuntimeInactiveTally:
    """Once-per-process summary of the dormant runtime-authority gate.

    ``InstallationService.resolve_active()`` returns ``None`` for every message
    until the installation tables are populated in a deployment, so the
    "webhook accepted while runtime inactive" line fired on 100% of production
    traffic. Logged per message at INFO it drowns every real signal, and an
    alert on it would page on all traffic while a genuine regression of the
    installation/authority rollout stayed invisible behind the noise. The line
    is therefore DEBUG, with a single INFO summary per process: the counter is
    operational context, never an alert condition (see docs/ops/incident-runbook.md).
    """

    def __init__(self) -> None:
        self.seen = 0

    def note(self, channel: str) -> int:
        self.seen += 1
        if self.seen == 1:
            logger.info(
                "webhook accepted while runtime inactive: no active installation; "
                "the runtime-authority gate is dormant for this process. Summary only — "
                "this signal must never alert. channel=%s",
                channel,
            )
        else:
            logger.debug(
                "webhook accepted while runtime inactive channel=%s seen=%d",
                channel,
                self.seen,
            )
        return self.seen

    def reset(self) -> None:
        """Clear the tally. Tests call this between cases."""
        self.seen = 0


_RUNTIME_INACTIVE = _RuntimeInactiveTally()


async def _runtime_authority_or_inactive(db: AsyncSession, *, channel: str):
    """Resolve active authority after signature verification and before any business write."""
    active = await InstallationService(db).resolve_active()
    if active is None:
        _RUNTIME_INACTIVE.note(channel)
        return None
    return active.fingerprint.stamp()


@router.post("/zalo/chatbot")
async def zalo_webhook(
    request: Request, db: AsyncSession = Depends(get_request_db)
) -> JSONResponse:
    # Per-IP limit before anything is read or parsed: an unauthenticated loop
    # must not reach the body read, the DB, or the enqueue (SEC-04).
    await enforce_webhook_rate_limit(request)
    t0 = time.time()  # webhook_ack SLO (Directive §1) — sampled on success
    # Read the raw body once for JSON parsing and signature verification.
    raw = await _read_body_within_limit(request)
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
        enqueue=enqueue_chat_turn_async,
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
    await enforce_webhook_rate_limit(request)
    t0 = time.time()  # webhook_ack SLO (Directive §1) — sampled on success
    raw = await _read_body_within_limit(request)
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
    # Multi-OA routing: the event names the OA that received it. A linked OA is
    # served under its own account key (own credentials, own send token); an
    # absent/unknown id falls back to the original OA, so an unlinked OA can
    # never be dropped and the single-OA deployment behaves exactly as before.
    from app.channels.providers.zalo_account import ZaloOaAccountResolver

    oa_account_key = await ZaloOaAccountResolver(db).account_key_for_payload(payload)
    result = await run_zalo_ingress(
        db,
        payload,
        enqueue=enqueue_chat_turn_async,
        channel="oa",
        runtime_authority=runtime_authority,
        account_key=oa_account_key,
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

    Rate-limited like the POSTs: this route does a DB read and a token compare
    for an unauthenticated caller. Meta sends the challenge once per
    subscribe/unsubscribe, so the per-IP budget never affects a real handshake.
    """
    from app.channels.providers.facebook_signature import constant_time_verify_token

    await enforce_webhook_rate_limit(request)
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
    await enforce_webhook_rate_limit(request)
    from app.channels.providers.facebook_messenger import FacebookMessengerNormalizer
    from app.channels.providers.facebook_signature import verify_messenger_signature

    t0 = time.time()
    raw = await _read_body_within_limit(request)
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

    # Get Started / m.me referral: the entry source (our ref, the ad behind a
    # Conversation ad) arrives in the postback BEFORE the candidate types, so
    # it is stamped here as a conversation-only touch. Best-effort like the
    # receipts above — a source hint never fails the ack.
    for psid, referral_attribution in normalizer.referrals_from_payload(
        payload, page_id=active.account_key
    ):
        try:
            await apply_messenger_referral(
                db,
                psid=psid,
                account_key=active.account_key,
                attribution=referral_attribution,
            )
        except Exception:  # noqa: BLE001
            logger.info("facebook referral attribution failed account_suffix=%s", active.account_key[-4:])

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
        # Fetch the sender's profile out of band. Gender is what lets the reply
        # say "anh"/"chị" rather than the neutral "anh/chị"; name and avatar
        # also populate the CRM. Enqueued (never awaited) so a slow Graph call
        # cannot delay the webhook acknowledgement, and swallowed because a
        # missing profile must never cost the candidate their bot turn.
        try:
            enqueue_messenger_profile_enrichment(
                psid=msg.identity.external_id, page_id=active.account_key
            )
        except Exception:  # noqa: BLE001 — enrichment is best-effort
            logger.info("facebook profile enrichment enqueue failed")
        # A Click-to-Messenger ad's pre-filled first message is page-initiated
        # content: Meta never opens the 24h reply window for it, so an
        # automated reply is always refused (code 10, subcode 2018278) and each
        # ad re-click would add another failed bubble. Park the thread for
        # human review instead of enqueueing a turn that cannot deliver.
        if msg.attribution is not None and msg.attribution.get("referral_source") == "ADS":
            try:
                if await escalate_messenger_ad_entry(db, outcome):
                    continue
            except Exception:  # noqa: BLE001 — escalation is best-effort; the
                # normal path below still applies rather than dropping the event
                logger.info(
                    "messenger ad-entry escalation failed conversation=%s",
                    outcome.conversation_id,
                )
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
