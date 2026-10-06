"""Static inventory gate for routes, queued work, outbox, and provider I/O.

Later authority-stamp work must update this explicit migration oracle whenever a
new producer or dispatch boundary is added.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

APP_DIR = Path(__file__).parents[1] / "app"
FIXTURE = Path(__file__).parent / "fixtures" / "universal_platform"

ROUTE_MODULE_CLASSIFICATION = {
    "auth": "auth_setup",
    "users": "auth_setup",
    "conversations": "active_kernel",
    "leads": "capability.recruitment",
    "notifications": "active_kernel",
    "knowledge": "capability.knowledge",
    "knowledge_bases": "capability.knowledge",
    "projects": "capability.recruitment",
    "jobs": "capability.recruitment",
    "dashboard": "capability.recruitment",
    "performance": "active_kernel",
    "integrations": "auth_setup",
    "installation": "auth_setup",
    "webhooks": "capability.channel.zalo",
}
DIRECT_ROUTE_CLASSIFICATION = {
    "/health": "public_ops",
    "/metrics": "public_ops",
    "/health/queue": "public_ops",
}
EXPECTED_ROUTE_COUNTS = {
    # Endpoint-level snapshot: adding a decorator inside an existing module must
    # fail this gate and force an explicit authority-classification review.
    "auth": 7,  # +1 server-side logout (SEC-03)
    "conversations": 19,  # -1 the conversation-scoped bot-run trace list (decision-trace removal)
    # +1 GET /by-contact-ids — batch contact→conversations lookup (max 200),
    # viewer-scoped, behind the dashboard candidate-card consolidation.
    "dashboard": 2,
    "integrations": 39,  # +3 custom OpenAI-compatible provider endpoints (settings page); +3 Jev decision-model endpoints; +2 geocoder credential endpoints (settings page)
    # +2 the TingTing support OA: save-and-check the four credentials (PUT /tingting)
    # and a re-probe endpoint (POST /tingting/oa/check)
    # +2 deployment-wide TingTing app API key (GET / PUT, secrets status-only)
    # +2 Meta App credentials UI; +4 multi-Page per-Page project CRUD
    # +1 admin-only credentials reveal (audited, no-store)
    # +3 candidate email digest: GET/PUT /email-digest config + POST test send
    "installation": 8,
    "jobs": 7,
    "knowledge": 14,  # -7 the legacy KB-version lane; -4 the Google Sheet external-source routes (0067)
    "knowledge_bases": 11,
    "leads": 16,  # +1 GET /{lead_id}/project-interests — project interest (2026-10-06)
    "main": 3,
    "notifications": 4,  # GET vapid-public-key, POST/DELETE subscriptions, POST test
    "performance": 2,
    # -4 single-page external-source-sync endpoints (Google Sheets retired, 0067)
    # +2 project external-API endpoints (get / put)
    # +1 project external-API admin test-call endpoint (post)
    "projects": 25,  # -4 Sheet sync routes; +1 admin-only GET /{id}/knowledge-export
    "users": 10,
    "webhooks": 4,  # Phase 5: +2 Facebook webhook routes (GET challenge + POST events)
}
# The legacy KB-version lane removal (-7 knowledge routes, -3 queue producers)
# is the re-review this digest records.
# 0062-era: +2 integrations routes — GET/PUT /api/v1/admin/integrations/geocoder
# (the admin-editable Google Maps credential behind the distance feature).
# 0066-era: -11 persona routes (the persona router, its adapter-assignment
# routes and its versions routes) — persona storage is a code constant now.
# 2026-era: -2 bot_runs routes (list + detail) — the Nhật ký bot log screen was
# removed; the BotRun telemetry table stays (the performance dashboard reads it).
# +4 notifications routes (VAPID key, subscribe, unsubscribe, self-test) — the
# Web Push handles behind the console's alert toggle; the alerts themselves are
# server-side (services/push), so no route carries them. The key handler reads
# `get_vapid_public_key` (renamed from `vapid_public_key` when the router became
# transport-only: config/ORM access moved into the service).
# 2026-10-06: +1 leads route (GET /{lead_id}/project-interests,
# capability.recruitment); digest recomputed from the post-change scan.
EXPECTED_ROUTE_INVENTORY_SHA256 = "e014bfb24322264e7361cef327be7e6439ca4e7c5b8c09e125150c83ceae8c01"
EXPECTED_BROAD_BOUNDARY_COUNTS = {
    # Scan the complete application tree so composition roots and bounded-context
    # adapters remain covered after transport logic moves out of legacy packages.
    "outbox_boundary": 8,
    # Same 10 sites; the claim_send / record_bot_outcome rows moved from
    # bot_path.py into send_claim.py / bot_outcome.py when the bot-send state
    # layer was split by change reason (file/scope keys only).
    # +2 for the Messenger User Profile API lookup (the Graph GET in
    # facebook_oauth.get_user_profile and the worker that calls it).
    # +7: the custom OpenAI-compatible probe + admin settings path; -2: the
    # degradation send left chatbot_worker (a suppressed turn sends nothing).
    # +3: the probe now reads finish_reason/usage and the reasoning-content
    # field so a reasoning model is not reported as a broken endpoint.
    # Same call site, second call: a version-less 404 base is retried once
    # with /v1 inserted (same host, same payload) — bumps the site's count
    # 1→2 without adding a distinct site.
    # Same site again: the OA user-detail error branch reads envelope.message
    # to tell a dead follower (-201 naming user_id) from a request bug —
    # bumps get_user_detail's get count 3→4, no new site.
    # +4: the gender judgment adds four dict `.get` lookups in
    # decisions.decide_turn (answers.get("gender"), the nested .get("choice"),
    # the confidence read, and answers.get("gender_stated")).
    # decisions.py carries get_http_client, so the provider_transport heuristic
    # counts every `.get` — dict reads included.
    # +1: decisions._retry_after_seconds reads two Retry-After headers with
    # `.get`; the heuristic counts the site once (rows are per (file, scope,
    # call), not per occurrence).
    # Same site, different verb: the OA refresh lock release became a Redis Lua
    # compare-and-delete (`eval`) instead of a blind `delete` (REL-03), so
    # integration_settings.refresh_oa_access_token contributes `eval` where it
    # used to contribute `delete` — one reviewed site either way, which is why
    # `eval` is in the scanned verb set.
    # +1: the OA sender's -201 unreachable classifier reads envelope.error /
    # envelope.message in zalo_oa_service._is_user_unreachable — one new
    # provider-transport `.get` site beside the existing result parsers.
    # +1: the Bot platform's send-result classifier
    # (zalo_bot_service._is_user_unreachable) reads the same error envelope
    # fields to tell a permanently invalid recipient (`user_id is invalid`) from
    # a transient failure — the bot-channel twin of the OA site above, and the
    # gate for the terminal-recipient mark.
    # +1 (since reversed by ARCH-21 below): the answer-completion guard added
    # _answer_was_cut, which reads the provider response metadata
    # (`finish_reason` / `stop_reason`) to tell a generation cut at the output
    # cap from a finished one. It landed in clients.py, which was a
    # provider-transport file, so both reads became one reviewed row.
    # +1: the per-project external API integration opens one egress site in
    # app/services/project/external_api.py (ProjectExternalApiService._send's
    # single `client.request`). The module imports `get_http_client`, so the
    # whole file is classified provider transport; keeping the outbound call in
    # one private method is what keeps this at one reviewed row.
    # +2: the deployment-wide TingTing integration adds app/services/tingting_api.py.
    # That module imports get_http_client, so the whole file is provider transport:
    # one reviewed egress row (TingtingApiService._send's single `client.request`)
    # plus its two `db.get` configuration reads — but the per-project integration
    # (-1 row: its egress site) was retired with the section it configured.
    # +2: multi-OA adds the per-account credential read (resolve_zalo) and the
    # account-scoped credential delete (clear_oa_account_credentials).
    # +2: the reset flow's channel scope reads the stored OA pin
    # (TingtingApiService.reset_oa_id's db.get) and the runner resolves the
    # conversation's channel account through the same provider-transport file.
    # +3: the reset flow keeps its state server-side (TingtingFlowStore), so
    # app/services/tingting_api.py gains a Redis `get` in load() plus the
    # `delete` in clear(), and the dispatcher names the send_tingting_otp tool
    # call — the flow tools themselves open no new egress site.
    # +2: the three-try verification cap (TingtingVerifyAttemptsStore, same
    # provider-transport file) adds a Redis `get` in count() and a `delete` in
    # reset(); record_failure's incr/expire are not scanned verbs — two
    # reviewed rows, no new egress site.
    # +1: the Messenger profile lookup now separates a refused object read
    # (code 100 / subcode 33) from a genuine rejection, so facebook_oauth gains
    # _error_subcode_from_envelope. Its envelope read is a dict `.get`, which
    # the provider_transport heuristic counts — the same treatment the sibling
    # _error_code_from_envelope already gets above.
    # -2: the zalo diagnostics probe (39fde21d, 2026-09-28) no longer holds a
    # token endpoint of its own — probe_zalo_oa_channel delegates the one
    # redemption to the provider, dropping its reviewed `get` (x4) and `post`
    # (x1) sites. Verified against a 39fde21d^ scan: same two rows, nothing
    # added anywhere. The 2026-09-28 graph typing work is scan-neutral.
    # +2: the escalation hotline became the admin-editable `tingting_hotline`
    # setting (operator rule 2026-09-29): TingtingApiService.hotline reads the
    # stored row and replace_hotline reads-then-writes it — the same two
    # configuration `get` reads their reset_oa_id siblings already have, no
    # new egress site.
    # +1: the geo-distance feature ("dự án nào gần nhà") adds exactly one
    # provider-transport site — app/services/geo/geocoding.py::geocode's
    # `client.get('/search')` against the Nominatim geocoder. The file stays
    # free of dict `.get` reads (indexing only), which is why the row is a
    # single `get` and not a family of them.
    # +2: the road-estimate feature adds the two matrix hops in
    # app/services/geo/providers.py — vietmap_matrix's `client.get('/api/matrix/v4')`
    # and google_distance_matrix's `client.get('/maps/api/distancematrix/json')`
    # — one reviewed row each. The service that ladders them
    # (services/geo/distance.py) holds no HTTP call of its own, so it adds
    # nothing here.
    # +2: the coordinate-verification feature adds the two reverse hops in
    # app/services/geo/providers.py — nominatim_reverse's `client.get('/reverse')`
    # and google_reverse's `client.get('/maps/api/geocode/json')` — one reviewed
    # row each. The containment check itself
    # (services/geo/verification.py) and the resolver
    # (services/geo/factory_point.py) import no HTTP client, so neither is a
    # provider-transport file and neither adds a row.
    # -1/+1: the keyless provider was then removed (2026-10-03). `nominatim_reverse`
    # goes with it, and so does `geocoding.geocode`'s `client.get('/search')` —
    # geocoding.py no longer imports an HTTP client at all, so that row leaves the
    # inventory and the file stops being provider transport. `google_reverse` stays
    # as the only reverse source. Net row count back to 96, with a different row
    # set: the digest moved, the count did not.
    # +5 candidate email digest: the generic Resend sender in email_service.py
    # (get + post inside send_email_via_resend), its two call sites in
    # services/email_digest/service.py (run_digest + send_test_digest), and the
    # admin test-send route in api/integrations.py.
    # +3 Web Push: the alert fan-out names its own delivery call `send_to_users`
    # (counted by the `send_` prefix at notify_admins, the notifications API and
    # the push service), and the OA refresh alert reads the provider's error
    # fields with one dict `.get` inside the provider-transport Zalo module.
    # None of the three is a new egress site: the HTTP call is pywebpush's, from
    # app/services/push/service.py.
    # +1 TingTing guide image: the outbox media payload routes send_payload to
    # the OA CS media template — one new `send_media` provider call in
    # app/services/zalo_sender.py, same Zalo OA transport as the text path
    # (no new provider, no new egress host).
    # 2026-10-05: +1 — the recruiter preparation chat status: one direct
    # `send_typing` call in app/services/chat_status.py (counted by the
    # `send_` prefix), routed through the existing Zalo Bot adapter's
    # `sendChatAction`. No existing row moved: dropping exactly that row from
    # the post-change scan reproduces the prior digest byte-for-byte.
    # 2026-10-06 (later): +1 — `_error_detail_from_envelope`, the new helper in
    # facebook_oauth.py that lifts Meta's `error.message` out of a Graph
    # rejection envelope (a provider-transport scope, so its two dict `.get`
    # reads count: the envelope lookup and the message lookup). This is how the
    # reason for a rejected send survives into `messages.external_error` instead
    # of collapsing to "messenger send rejected". Verified: reverting both
    # provider files to their pre-change state reproduces the prior digest
    # byte-for-byte, so this single site is the whole difference. (The adapter's
    # new logging is scan-neutral.)
    "provider_boundary": 101,
    # -32: the integrations router became transport-only. Its 30+ rows were
    # mostly route-decorator artifacts of the forced by-path scan (every
    # `@router.get` counted as a provider `get`); the real transport sites
    # moved with their logic — the OA diagnostic OAuth POST and the bot probe
    # reads into services/integrations/zalo_diagnostics.py (forced by path,
    # same treatment the router had), while the LLM probe request-merging
    # reads landed in llm_diagnostics.py, which is not a provider-transport
    # file. The Graph calls of the Facebook flow were already inventoried at
    # their channels/providers home and are unchanged.
    # -8: the integration_settings decomposition split the single module into a
    # package; the OA refresh transport (post + eval + its surrounding reads)
    # moved into providers/zalo.py, which still carries the get_http_client
    # marker, while the LLM/Facebook resolve `._load` dict reads and the
    # storage-layer db.get upserts landed in modules that are not
    # provider-transport files. The call sites themselves are unchanged, only
    # their home module moved.
    # -3: the clients.py decomposition moved the routed-prefetch wrapper and the
    # job-authority readers (dict `.get` rows) into prefetch.py / grounding.py,
    # which are not provider-transport files; the call sites themselves are
    # unchanged, only their home module moved.
    # -5: the clients.py split moved the embedding transport into
    # graph/embedders.py, which is still a provider-transport file and keeps the
    # one real egress site (`OpenRouterEmbedder.batch`'s `client.post` plus its
    # three response reads) under the same two reviewed rows — only the home
    # module changed. What dropped is the collateral: clients.py carried the
    # `get_http_client` marker only because the embedder lived there, so every
    # dict `.get` in the agent loop (`agent`, `agent._dispatch_one`, `direct`),
    # the provider default lookup (`_active_llm_provider`, now in providers.py)
    # and the finish-reason reads (`_answer_was_cut`, now in answer_repair.py)
    # were being scanned as egress. None of those modules is provider transport,
    # so five reviewed rows go away and no egress site left the inventory — the
    # same treatment the earlier prefetch.py / grounding.py moves got.
    # +3 for the Messenger profile-enrichment chain, which fetches the sender's
    # gender so replies can address them as anh / chị:
    # webhooks.facebook_webhook -> composition.enqueue_messenger_profile_enrichment
    # -> persistence_worker.enqueue_enrich_messenger_profile -> enqueue_job.
    # +1: a turn that held the per-chat mutex hands the conversation to a newer
    # inbound the ingress guard dropped, via chatbot_worker._handoff_to_newer_inbound
    # -> enqueue_latest_unanswered_worker_message.
    "queue_producer": 29,  # -3 legacy KB-version lane; -8 Google Sheet sync producers (0067)
    # -1: the custom provider stopped reading a stored context-window row (the
    # field left the settings UI), so resolve_custom_llm._load's `get` count
    # drops 7→6 at the same site.
    # -1: the direct-context capacity resolver no longer calls the OpenRouter
    # model-metadata endpoint (every chatbot agent now runs the fixed 1M window),
    # removing knowledge_base_capacity's provider-transport `get` site.
    # +1: recovered turns go to their own low-priority queue, so the sweep's
    # enqueue site is enqueue_recovery_chat_run instead of enqueue_chat_run.
}
# Digest refresh only: webhook.ZaloWebhookService.handle replaced its two
# post-write `svc.get(conv.id)` re-reads with the column-scoped
# `db.refresh(conv, _GUARD_REFRESH_COLUMNS)`, so the `get` invocation count at
# that one reviewed site drops 3→1. No site was added, removed, or moved, so
# EXPECTED_BROAD_BOUNDARY_COUNTS (distinct call sites) is unchanged.
# ARCH-20 moved graph/runner.py's outbound half into graph/dispatch.py:
# _dispatch_claimed_message's two `send_message` calls and _status_heartbeat's
# `send_chat_action` are the same reviewed sites, re-keyed from
# `app/graph/runner.py` to `app/graph/dispatch.py` (same scope, same count), so
# EXPECTED_BROAD_BOUNDARY_COUNTS is unchanged by that split. The digest covers
# the file key, so it must be recomputed whenever a call site changes home.
# ARCH-21 moved the OpenRouter embedding POST out of clients.py into
# graph/embedders.py: the same two reviewed rows, re-keyed to their new home.
# The count change is the -5 explained above. The digest covers the file key,
# so it had to be recomputed for the move as well.
# The conversation split re-homed three reviewed outbox sites from
# app/services/conversation/__init__.py into service.py and one from
# recruiter_path.py into recruiter_receipts.py: same scope, same call, same
# count, so EXPECTED_BROAD_BOUNDARY_COUNTS is unchanged and only the digest
# (which covers the file key) moves.
# 2026-09-28: 39fde21d removed probe_zalo_oa_channel's own token-endpoint
# redemption (the -2 provider_boundary sites above); digest recomputed from the
# post-change scan. The 2026-09-28 graph typing work (OPS-30) is scan-neutral,
# confirmed by comparing the scan against a git archive of HEAD.
# 2026-09-29: enqueue_job's canceled-job recovery path re-submits with a direct
# `q.enqueue(...)` call instead of the `retry_submit = q.enqueue` alias (the
# alias could NameError when the original failure preceded the assignment).
# Same scope, same reviewed site, +1 `enqueue` invocation; fixture row and
# digest recomputed from the post-change scan.
# 2026-09-29 (later): the escalation hotline became the admin-editable
# `tingting_hotline` setting — TingtingApiService.hotline and replace_hotline
# add two reviewed configuration `get` rows (+2 provider_boundary, annotated
# at the count above); digest recomputed from the post-change scan.
# 2026-09-30: the projects-not-jobs migration removed the sort_by Jev question
# and its answer parse from graph/decisions.py — a provider-transport file, so
# its dict `.get` reads count — dropping two `get` invocations at the one
# `JevDecisionClient.decide_turn` reviewed site (20→18). No site was added,
# removed, or moved, so EXPECTED_BROAD_BOUNDARY_COUNTS is unchanged; the digest
# was recomputed from the post-change scan and the prior digest reconstructs
# exactly from that single count change, so nothing else moved.
# Bounded channel dispatch adds the reviewed `_send_parts` adapter.send_text
# boundary. Each part reuses the same provider and authority/policy fences;
# no provider endpoint, registry binding, or queue/outbox writer was added.
# 2026-10-01: the geo-distance feature added the geocoder as a provider: one
# reviewed row, app/services/geo/geocoding.py::geocode's `client.get('/search')`
# (+1 provider_boundary, annotated at the count above). Digest recomputed from
# the post-change scan.
# provider_boundary +1: app/services/geo/providers.py — the Google geocoding
# adapter's /maps/api/geocode/json call (tried before the Nominatim ladder when
# an admin has configured a key).
# provider_boundary +1: the same file — the Vietmap geocoding adapter, now the
# primary hop ahead of Google. Its two calls are /api/search/v4 (returns a
# ref_id, no coordinates) and /api/place/v4 (resolves that ref_id to lat/lng);
# one reviewed row, since the scan keys on file+scope+call and the pair share
# the vietmap_geocode scope. No other boundary moved: the Nominatim ladder, the
# 1 req/s throttle, the durable geocode_cache mapping and the admin credential
# routes are all unchanged. Digest recomputed from the post-change scan.
# 2026-10-03: the real-intention gate added the `job_seeking` answer parse to
# JevDecisionClient.decide_turn (a provider-transport scope, so its dict `.get`
# reads count) — +2 `get` invocations at that one reviewed site (18→20: one
# `answers.get("job_seeking")`, one `.get("choice")`). No site was added,
# removed, or moved, so EXPECTED_BROAD_BOUNDARY_COUNTS is unchanged; the digest
# was recomputed from the post-change scan and the prior digest reconstructs
# exactly from that single count change (verified by re-hashing the scan with
# the count reverted to 18), so nothing else moved.
# 2026-10-03: the road-estimate feature added the two matrix hops in
# app/services/geo/providers.py (vietmap_matrix, google_distance_matrix) — two
# new provider_boundary rows, no existing row moved: dropping exactly those two
# rows from the post-change scan reconstructs the prior pin byte-for-byte
# (verified by re-hashing). Counts annotated at `provider_boundary` above.
# 2026-10-03: the coordinate-verification feature added the two reverse hops in
# app/services/geo/providers.py (nominatim_reverse, google_reverse) — the same
# +2 shape, annotated at `provider_boundary` above. Dropping exactly those two
# rows from the post-change scan reconstructs the prior pin byte-for-byte
# (verified by re-hashing); services/geo/verification.py and factory_point.py
# are not provider-transport files, so they contribute nothing.
# 2026-10-03 (later): the keyless provider was removed. `nominatim_reverse` and
# `geocoding.geocode`'s `client.get('/search')` both leave the inventory (-2
# rows, and geocoding.py stops being a provider-transport file), so the row count
# returns to 96 while the row set does not: the digest was recomputed from the
# post-change scan. Two invocation counts inside surviving rows moved with it,
# neither adding a row — google_geocode's `get` 5→6 (the coarse-`types` read that
# replaced the ladder's precision gate) and decisions.decide_turn's `get` 20→21
# (unrelated prompt work on the employee_support intent, landed concurrently).
# 0066-era: -2 outbox_boundary (the proactive turn's
# prepare_proactive_message/record_proactive_outcome write path) and
# -2 queue_producer (the removed followup tick and its enqueue),
# -1 provider_boundary (the proactive send). Digest recomputed.
# 2026-10-05: +1 provider_boundary (the chat_status preparation pulse above);
# digest recomputed from the post-change scan.
# 2026-10-06: the two new Jev answer parses in JevDecisionClient.decide_turn
# (`self_checkin`, `wage_wait` — a provider-transport scope, so its dict `.get`
# reads count) moved that site's `get` 21→23. No site was added, removed, or
# moved, so EXPECTED_BROAD_BOUNDARY_COUNTS is unchanged; the digest was
# recomputed from the post-change scan and the prior digest reconstructs
# exactly from that single count change (verified by re-hashing the scan with
# the count reverted to 21), so nothing else moved.
# 2026-10-06 (later): the new `_error_detail_from_envelope` transport helper
# (+1 provider_boundary at the annotated count above), so the digest was
# recomputed from the post-change scan.
EXPECTED_BROAD_BOUNDARY_SHA256 = "ff771697e2873ff34cb9587eb5465d2b3e3b095ac2da0bd1e417b16dfcfe35dd"
CALL_CATEGORIES = {
    "queue_producer": {
        "enqueue",
        "enqueue_job",
        "enqueue_chat_run",
        "enqueue_recovery_chat_run",
        "enqueue_persist_candidate",
        "enqueue_enrich_oa_profile",
        "enqueue_followup",
        "enqueue_ingest",
    },
    "outbox_boundary": {
        "enqueue_outbox",
        "create_pending_outbox",
        "dispatch_outbox",
        "dispatch_message_outbox",
    },
    "provider_boundary": {"send_message", "send_chat_action", "send_payload"},
}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


class _CallInventory(ast.NodeVisitor):
    def __init__(self, relative_path: str, *, provider_transport: bool) -> None:
        self.relative_path = relative_path
        self.provider_transport = provider_transport
        self.scope: list[str] = []
        self.items: list[tuple[str, str, str, str]] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        for category, names in CALL_CATEGORIES.items():
            if name in names:
                self.items.append(
                    (category, self.relative_path, ".".join(self.scope) or "<module>", name)
                )
                break
        self.generic_visit(node)


class _BroadCallInventory(_CallInventory):
    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        if name is None:
            self.generic_visit(node)
            return
        categories: list[str] = []
        if "outbox" in name and name.startswith(("create", "enqueue", "dispatch")):
            categories.append("outbox_boundary")
        elif "enqueue" in name:
            categories.append("queue_producer")
        if name.startswith("send_") or (
            self.provider_transport
            # `eval` is the Redis Lua CAS the ownership-checked lock releases
            # use (REL-03); it mutates state, so it belongs in the snapshot
            # the same way `delete` did.
            and name
            in {"get", "getdel", "post", "put", "patch", "delete", "request", "eval"}
        ):
            categories.append("provider_boundary")
        for category in categories:
            self.items.append(
                (category, self.relative_path, ".".join(self.scope) or "<module>", name)
            )
        self.generic_visit(node)


def _included_router_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "include_router" or not node.args:
            continue
        router = node.args[0]
        if isinstance(router, ast.Attribute) and isinstance(router.value, ast.Name):
            modules.add(router.value.id)
    return modules


def _direct_routes(tree: ast.AST) -> set[str]:
    return {record[1] for record in _decorated_routes(tree)}


def _decorated_routes(tree: ast.AST) -> list[tuple[str, str, str, str]]:
    routes: list[tuple[str, str, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                continue
            router_name = (
                decorator.func.value.id
                if isinstance(decorator.func.value, ast.Name)
                else "<unknown>"
            )
            routes.append(
                (decorator.func.attr.upper(), str(decorator.args[0].value), node.name, router_name)
            )
    return routes


def _router_prefixes(tree: ast.AST) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if (
            not isinstance(node.value.func, ast.Name)
            or node.value.func.id != "APIRouter"
            or len(node.targets) != 1
            or not isinstance(node.targets[0], ast.Name)
        ):
            continue
        prefix = ""
        for keyword in node.value.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                prefix = str(keyword.value.value)
        prefixes[node.targets[0].id] = prefix
    return prefixes


def _route_records() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for module, category in ROUTE_MODULE_CLASSIFICATION.items():
        tree = ast.parse((APP_DIR / "api" / f"{module}.py").read_text(encoding="utf-8"))
        prefixes = _router_prefixes(tree)
        api_prefix = "" if module == "webhooks" else "/api/v1"
        for method, path, function, router_name in _decorated_routes(tree):
            records.append(
                {
                    "module": module,
                    "method": method,
                    "path": f"{api_prefix}{prefixes.get(router_name, '')}{path}",
                    "function": function,
                    "classification": category,
                }
            )
    main_tree = ast.parse((APP_DIR / "main.py").read_text(encoding="utf-8"))
    for method, path, function, _router_name in _decorated_routes(main_tree):
        if path in DIRECT_ROUTE_CLASSIFICATION:
            records.append(
                {
                    "module": "main",
                    "method": method,
                    "path": path,
                    "function": function,
                    "classification": DIRECT_ROUTE_CLASSIFICATION[path],
                }
            )
    return sorted(records, key=lambda item: (item["path"], item["method"], item["function"]))


def _runtime_calls(*, broad: bool = False) -> list[dict]:
    counter: Counter[tuple[str, str, str, str]] = Counter()
    for path in sorted(APP_DIR.rglob("*.py")):
        relative_path = path.relative_to(APP_DIR.parent).as_posix()
        source = path.read_text(encoding="utf-8")
        # The Zalo diagnostics module issues the raw OA OAuth POST through the
        # integration HTTP client without importing httpx itself, so it is
        # forced into the reviewed surface by path — the same treatment the
        # integrations router received before the probes moved out of it.
        provider_transport = any(
            marker in source for marker in ("get_http_client", "import httpx", "from httpx")
        ) or relative_path.endswith("services/integrations/zalo_diagnostics.py")
        visitor_type = _BroadCallInventory if broad else _CallInventory
        visitor = visitor_type(relative_path, provider_transport=provider_transport)
        visitor.visit(ast.parse(source))
        counter.update(visitor.items)
    return [
        {"category": category, "file": file, "scope": scope, "call": call, "count": count}
        for (category, file, scope, call), count in sorted(counter.items())
    ]


def test_every_registered_router_and_direct_route_has_an_authority_classification():
    main_tree = ast.parse((APP_DIR / "main.py").read_text(encoding="utf-8"))

    assert _included_router_modules(main_tree) == set(ROUTE_MODULE_CLASSIFICATION)
    assert _direct_routes(main_tree) == set(DIRECT_ROUTE_CLASSIFICATION)


def test_every_classified_router_contains_at_least_one_http_route():
    for module in ROUTE_MODULE_CLASSIFICATION:
        tree = ast.parse((APP_DIR / "api" / f"{module}.py").read_text(encoding="utf-8"))
        assert _direct_routes(tree), f"{module} has no inventoried route"


def test_every_http_endpoint_matches_the_reviewed_authority_snapshot():
    records = _route_records()
    counts = Counter(record["module"] for record in records)
    digest = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert dict(sorted(counts.items())) == EXPECTED_ROUTE_COUNTS
    assert digest == EXPECTED_ROUTE_INVENTORY_SHA256
    assert all(
        record["classification"] in {"public_ops", "auth_setup", "active_kernel"}
        or record["classification"].startswith("capability.")
        for record in records
    )


def test_queue_outbox_and_provider_boundaries_match_the_explicit_inventory():
    expected = json.loads((FIXTURE / "runtime_surface_inventory.json").read_text(encoding="utf-8"))
    actual = _runtime_calls()

    assert actual == expected
    assert {item["category"] for item in actual} == set(CALL_CATEGORIES)


def test_broad_side_effect_scan_matches_reviewed_boundary_snapshot():
    actual = _runtime_calls(broad=True)
    counts = Counter(item["category"] for item in actual)
    digest = hashlib.sha256(
        json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert dict(sorted(counts.items())) == EXPECTED_BROAD_BOUNDARY_COUNTS
    assert digest == EXPECTED_BROAD_BOUNDARY_SHA256
