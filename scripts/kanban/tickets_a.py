"""Security + reliability tickets."""

# Ticket ids that were allocated, then withdrawn by request before the board was
# published. They are deliberately NOT in ``TICKETS``: no id is ever renumbered,
# so the security sequence starts at SEC-02 and that gap is intentional.
WITHDRAWN = [
    dict(
        id="SEC-01",
        title="Unauthenticated Zalo OA webhook (`POST /webhooks/zalo/oa`)",
        reason=(
            "The stored credential is the OA *access-token* secret rather than Zalo's "
            "webhook checksum key, so wiring the (correct) verifier in without the "
            "matching credential would false-reject 100% of real OA events."
        ),
    ),
]

TICKETS = [
    dict(
        id="SEC-02",
        column="DEV_COMPLETED",
        title="Lead by-id routes skip the viewer-scope invariant (IDOR on candidate PII)",
        sev="high",
        area="security",
        labels=["security", "reliability"],
        effort="M",
        evidence_log=[
            'ee0e28e5 — by-id reads scoped to the viewer, 404 on out-of-scope ids',
            'tests/test_lead_viewer_scope.py (61 tests) — 404 read+mutate, admin/own/unassigned 200, viewer threaded, bot_runs projection',
        ],
        problem=(
            "`GET/PATCH /leads/{id}` and every lead sub-resource load the row by primary key with no "
            "ownership predicate, so any authenticated recruiter can read and mutate every other "
            "recruiter's candidate PII. The list/board queries and the conversation detail path both "
            "enforce the invariant; the lead by-id path does not, which makes this an omission rather "
            "than a deliberate org-wide policy."
        ),
        evidence=[
            "`backend/app/api/leads.py:47-57` — `_load(lead_id, db)` takes no viewer.",
            "`backend/app/services/lead/service.py:52-58` — `get()` is a plain `db.get(Lead, lead_id)`; `update`/`assign`/`set_stage` apply no ownership check.",
            "`backend/app/services/lead/service.py:75` — list *does* apply `viewer_scope_filter(...)`; `backend/app/services/conversation/repository.py:156-162` scopes conversation detail the same way.",
            "`backend/app/api/leads.py:40-44` — the route gate is `require_capability_or_legacy(\"candidate_intake\")`, an installation capability, not a role.",
            "`backend/app/schemas/lead.py:18-35` — `LeadOut` exposes name, phone, address, notes.",
            "Related: `backend/app/api/bot_runs.py:32-42,45-60` is org-wide for both roles and its projection can echo `proposed_reply` for conversations the caller cannot open.",
        ],
        impact=(
            "Sequential integer ids make enumeration trivial: full candidate PII for the whole tenant, "
            "`/assist` chatops content derived from another recruiter's conversation, and "
            "`POST /{id}/assign {\"recruiter_id\": \"<self>\"}` to steal any lead."
        ),
        fix=(
            "Thread the viewer through the lead read path as conversations do: add "
            "`LeadRepository.get_visible` mirroring `viewer_can_access_lead` "
            "(`backend/app/services/viewer_scope.py:70-77`), return **404** rather than 403 so ids are "
            "not probeable, and apply it to every by-id route plus `LeadService.update/assign/"
            "set_stage/create_followup/replace_manual_tags`. Validate `AssignRequest.recruiter_id` "
            "resolves to an enabled user. Scope the `/bot_runs` projection or drop `proposed_reply` "
            "from the list response."
        ),
    ),
    dict(
        id="SEC-03",
        column="DEV_COMPLETED",
        title="No server-side logout; refresh tokens are neither revoked nor truly rotated",
        sev="high",
        area="security",
        labels=["security"],
        effort="M",
        evidence_log=[
            'd117e086 — POST /auth/logout bumps token_version, refresh rejects a stale ver, email change bumps it',
            'tests/test_auth_token_revocation.py — old refresh/access tokens die at logout, fresh login works, route contract',
        ],
        problem=(
            "There is no `/auth/logout`. `POST /auth/refresh` re-issues a token pair without "
            "invalidating the token it consumed, so a stolen 14-day refresh token survives the "
            "victim's logout and is indistinguishable from legitimate rotation."
        ),
        evidence=[
            "`backend/app/api/auth.py` — the whole auth surface is login / forgot-password / reset-password / refresh / me / change-password; no logout route.",
            "`backend/app/identity/infrastructure/http.py:73-93` — refresh validates `type`/`user`/`disabled`/`ver`, then mints new tokens; the presented token is never invalidated. No jti or generation store exists anywhere in `app/`.",
            "`backend/app/core/config.py:107-108` — access token 60 min, refresh token 14 days.",
            "Frontend logout only clears `localStorage` (`frontend/src/components/atomic-crm/providers/rest/authProvider.ts`).",
        ],
        impact=(
            "An exfiltrated refresh token grants access for up to 14 days; logout is cosmetic; the "
            "theft is undetectable from token traffic. Compounded by the absence of CSP with JWTs in "
            "`localStorage` (SEC-06)."
        ),
        fix=(
            "Add `POST /api/v1/auth/logout` that bumps `user.token_version` — both token types already "
            "carry and check `ver` (`backend/app/identity/application/authentication.py:42-43`, "
            "`backend/app/identity/infrastructure/http.py:94`), making this the cheapest correct fix. For real "
            "rotation, store a per-user refresh generation and reject a stale one so a replay "
            "invalidates the family. Also bump `token_version` on email change "
            "(`backend/app/services/user_service.py:125-126,141`)."
        ),
    ),
    dict(
        id="SEC-04",
        column="DEV_COMPLETED",
        title="Rate limiting covers only the four auth endpoints; webhooks and LLM routes are unbounded",
        sev="medium",
        area="security",
        labels=["security", "performance"],
        effort="M",
        evidence_log=[
            'aeb78362 — per-user buckets on the LLM routes, per-IP on the webhook POSTs, fail_open switch',
            'tests/test_ratelimit.py — bucket isolation per route and per user, fail-open vs fail-closed',
        ],
        problem=(
            "The only configured limits are on login / forgot-password / reset-password / refresh. "
            "Every LLM- or embedding-backed route and all webhook POSTs are unbounded, and the limiter "
            "fails open on Redis errors."
        ),
        evidence=[
            "`backend/app/identity/infrastructure/rate_limits.py` — the complete configured surface; `backend/app/api/auth.py:20-25` is its only importer.",
            "Unbounded expensive routes: `POST /jobs/search` (`backend/app/api/jobs.py:96-106`), `POST /projects/{id}/rag/test` (`backend/app/api/knowledge.py:229`), `GET /leads/{id}/assist`, `POST /leads/{id}/chatops-actions/*`, `POST /conversations/{id}/web-chat-turn` (`backend/app/api/conversations.py:409`), and all four webhook POSTs.",
            "`backend/app/core/ratelimit.py:60-70` fails open on any Redis exception; `:32-39` trusts the first `X-Forwarded-For` hop for bucketing.",
        ],
        impact=(
            "An authenticated recruiter firing N parallel `/web-chat-turn` or `/jobs/search` requests "
            "drains the deployment-wide LLM/embed token lists (`llm_concurrency_limit=8`, "
            "`embed_concurrency_limit=6`) and suppresses genuine candidate turns by the configured "
            "fail-fast contract."
        ),
        fix=(
            "Add an IP limiter on the four webhook routes and a per-user limiter on `/jobs/search`, "
            "`/rag/test`, `/web-chat-turn`, `/assist`, `/chatops-actions/*`. Consider fail-closed for "
            "the LLM bucket while leaving auth fail-open."
        ),
    ),
    dict(
        id="SEC-05",
        column="DEV_COMPLETED",
        title="Upload size caps exist but are dead code; request bodies are read unbounded",
        sev="medium",
        area="security",
        labels=["security", "reliability"],
        effort="S",
        evidence_log=[
            'c2b46788 — upload cap after every read, Content-Length pre-check and 1 MiB ceiling on webhook bodies (413)',
            'tests/test_upload_size_guard.py, tests/test_webhook_ingress_limits.py',
        ],
        problem=(
            "The intended 20 MiB upload cap and the zip-bomb guard have no production call site, and "
            "every upload and webhook handler reads the entire body into memory before any check."
        ),
        evidence=[
            "`backend/app/services/ingestion/limits.py:13,47-55` — `MAX_UPLOAD_BYTES`, `assert_upload_size`, `assert_archive_metadata`; a repo-wide grep finds only `backend/tests/test_generic_source_blocks.py:9-13,63-66`.",
            "`backend/app/api/knowledge.py:387-398` and `backend/app/services/knowledge/service.py:355` — `data = await file.read()` then `upload_bytes(...)`; `backend/app/api/personas.py:154-161` reads with no cap at all.",
            "`backend/app/api/webhooks.py:66-90` — `await request.body()` on all three POST routes (`:101`, `:148`, `:243`).",
        ],
        impact=(
            "An admin-scoped session POSTs a multi-gigabyte body: the ASGI layer buffers it, "
            "`file.read()` materialises a second full copy, and it is written to the uploads volume. "
            "The web container has no memory limit (OPS-09) on a 4 GB host."
        ),
        fix=(
            "Call `assert_upload_size(len(data))` immediately after every `file.read()` and check "
            "`Content-Length` before `request.body()`; return 413. Enforce a hard `max_body_size` at "
            "Caddy/uvicorn as the outer bound, since FastAPI has none."
        ),
    ),
    dict(
        id="SEC-06",
        column="DEV_COMPLETED",
        title="No security headers and no CSP; JWTs live in localStorage",
        sev="medium",
        area="security",
        labels=["security"],
        effort="S",
        evidence_log=[
            '1be1b2d0 + 3cabb7b4 — CSP/X-Frame-Options/Permissions-Policy on the deploy-rendered template, TrustedHostMiddleware',
            'tests/test_security_headers.py, tests/test_allowed_hosts_config.py',
        ],
        problem=(
            "The application sets no HSTS / CSP / X-Frame-Options / X-Content-Type-Options / "
            "Referrer-Policy, and the only edge config that could set them is rendered on the host and "
            "absent from the repo."
        ),
        evidence=[
            "`backend/app/main.py:189-195` — the only middleware is `CORSMiddleware`; no `TrustedHostMiddleware`.",
            "`frontend/index.html` has no CSP meta; a repo-wide grep for those header names finds them only inside `.claude/skills/` reference docs.",
            "`backend/docker-compose.yml` (caddy service) mounts `./Caddyfile`, which `backend/scripts/flip_caddy.sh` renders at deploy time — so this could **not** be verified from the repo. Confirm on the host before treating as confirmed.",
            "`frontend/src/lib/apiClient.ts:12-13` — the JWT pair sits in `localStorage` under `RaStore.auth.*`.",
        ],
        impact=(
            "Any script execution is silent full account takeover, with a 60-minute access token and a "
            "14-day refresh token that cannot be revoked (SEC-03). Without "
            "`X-Frame-Options`/`frame-ancestors` the console is also clickjackable."
        ),
        fix=(
            "Add to the deploy-rendered Caddy config: `Strict-Transport-Security`, "
            "`Content-Security-Policy: default-src 'self'; object-src 'none'; frame-ancestors 'none'` "
            "(verify whether Tailwind-injected styles need `style-src 'unsafe-inline'`), "
            "`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, "
            "`Permissions-Policy`. Add `TrustedHostMiddleware` to `main.py`. Keep the declaration in "
            "the deploy template so a redeploy cannot lose it."
        ),
    ),
    dict(
        id="SEC-07",
        column="DEV_COMPLETED",
        title="Admin secret previews leak 8 characters of every credential; reveal endpoint has no step-up",
        sev="medium",
        area="security",
        labels=["security"],
        effort="S",
        evidence_log=[
            'a0f7d807 — secrets report configured+length only; reveal requires password step-up and is audited',
            'tests/test_integration_settings.py, tests/test_integrations_api.py, tests/test_facebook_oauth.py',
        ],
        problem=(
            "Every stored integration secret is returned to admin GETs as `first4...last4`, and the "
            "Facebook reveal endpoint returns the Meta app secret in plaintext with no "
            "re-authentication."
        ),
        evidence=[
            "`backend/app/services/integration_settings.py:350-366` — `_preview()` returns `f\"{value[:4]}...{value[-4:]}\"`; attached at `:465-473`, `:501`, `:540`, `:591`, `:629`, `:1099-1104`.",
            "`backend/app/api/integrations.py:1116-1145` — `POST /admin/integrations/facebook/credentials/reveal` returns `facebook_app_secret` and the webhook verify token in plaintext; `require_admin` + `no-store` + actor logged, but no step-up.",
        ],
        impact=(
            "Eight characters of every credential narrow brute force, and the Meta app secret is the "
            "HMAC key that authenticates every Facebook webhook — possessing it converts to forging "
            "inbound Messenger events. Any live admin session can retrieve it."
        ),
        fix=(
            "Replace character previews with a `configured: true` / length-only status for authorizing "
            "secrets, keeping `_preview` only for non-authorizing identifiers. Require password "
            "re-entry or a short-lived single-use token on the reveal endpoint and audit-log the reveal."
        ),
    ),
    dict(
        id="SEC-08",
        column="DEV_COMPLETED",
        title="JWT validation omits audience/issuer and required claims; algorithm is env-controlled",
        sev="medium",
        area="security",
        labels=["security"],
        effort="S",
        evidence_log=[
            '97db619e — iss/aud minted and verified, required claims, algorithm allowlist at boot',
            'tests/test_security.py',
        ],
        problem=(
            "Decode passes no `audience`, no `issuer`, and no `options={\"require\": [...]}`, and "
            "`jwt_algorithm` is an unvalidated environment string."
        ),
        evidence=[
            "`backend/app/core/security.py:65-72` — `jwt.decode(token, secret, algorithms=[_settings.jwt_algorithm])`.",
            "`backend/app/core/config.py` — `jwt_algorithm: str = \"HS256\"` with no `field_validator`.",
            "Not exploitable today: `type`/`ver`/`disabled` are checked and the subject must parse as a UUID, and `alg: none` is unreachable because PyJWT rejects a non-`None` key.",
        ],
        impact=(
            "Real exposure is misconfiguration and cross-boundary reuse: a smuggled algorithm value "
            "(e.g. `RS256`) silently breaks signing and turns logins into 500s with no boot-time guard, "
            "and if any sibling service is ever pointed at the same secret, tokens become "
            "interchangeable across trust boundaries. Note `jwt_secret` also serves as the "
            "integration-settings cipher-key fallback (`backend/app/services/integration_settings.py:299`) "
            "— a key-reuse smell."
        ),
        fix=(
            "Add `aud`/`iss` on issue and require them on decode; add "
            "`options={\"require\": [\"exp\", \"sub\", \"type\", \"ver\"]}`; add a "
            "`field_validator(\"jwt_algorithm\")` allowlisting HS256/384/512 so a bad value fails at "
            "boot. Derive the cipher key from a labeled input (e.g. `sha256(\"secret-store-v1:\" + key)`) "
            "instead of reusing `jwt_secret`."
        ),
    ),
    dict(
        id="REL-01",
        column="DEV_COMPLETED",
        title="A partially delivered multi-bubble answer is recorded FAILED, so recovery answers again",
        sev="high",
        area="reliability",
        labels=["reliability"],
        effort="M",
        evidence_log=[
            'fb344ee0 — partial delivery flagged, SEND_UNKNOWN instead of FAILED, provider-id rows excluded from recovery',
            'tests/test_zalo_bot_service.py, tests/test_graph_runner_turn.py, tests/test_reconcile_worker.py; integration/test_reconcile_superseded_inbound.py',
        ],
        problem=(
            "Answers longer than 420 characters are sent as N separate provider requests. When chunk N "
            "fails with a *definite* provider error, the aggregate result is `ok=False` carrying chunk "
            "1's message id and a null error class — which is recorded as `FAILED`, after which the "
            "reconcile sweep treats it as a lost turn and re-answers the candidate."
        ),
        evidence=[
            "`backend/app/services/zalo_bot_service.py:105-106` — `ZALO_VISIBLE_BUBBLE_CHARS = 420`, so any answer over 420 chars is multi-request.",
            "`backend/app/services/zalo_bot_service.py:223-283` (`_aggregate_chunked_send`) — on failure returns `ok=False`, `msg_id=message_ids[0]` (`:277`), `error_class=result.error_class` (`:280`).",
            "`backend/app/graph/runner.py:1095-1104` — only `AMBIGUOUS_SEND_CLASSES` map to SEND_UNKNOWN, so a definite mid-chunk failure becomes `FAILED` (`backend/app/services/conversation/bot_path.py:620-636`).",
            "`backend/app/services/conversation/repository.py:603-620` admits a newest BOT message with `delivery_status IN ('PENDING','SENDING','FAILED')`; `backend/app/workers/reconcile_worker.py:298-311` classifies it `failed_send` and re-enqueues after the 900 s backoff (`:93`).",
        ],
        impact=(
            "On the Zalo Bot channel there are no receipts, so the FAILED row is permanent and the "
            "duplicate reply is deterministic — the candidate gets the answer twice, including chunk 1 "
            "twice. On the OA channel a `user_received_message` receipt for chunk 1 can rescue the row "
            "(`receipt_advances(FAILED, DELIVERED)`), which is why this is intermittent rather than "
            "universal. A chunk failing with a *transport* error is correctly routed to SEND_UNKNOWN "
            "and is not affected."
        ),
        fix=(
            "Make `_aggregate_chunked_send` distinguish partial delivery: when `message_ids` is "
            "non-empty, return SEND_UNKNOWN (at-most-once) or a dedicated `partial` outcome — never a "
            "bare `ok=False` with a null error class. Persist one `Message` row per bubble (or a "
            "`provider_message_ids` list) so partial delivery is representable, and exclude `FAILED` "
            "rows with a non-null `zalo_message_id` from the `failed_send` recovery branch."
        ),
    ),
    dict(
        id="REL-02",
        column="DEV_COMPLETED",
        title="Blocking synchronous Redis runs on the event loop in LLM telemetry and the semaphore release",
        sev="high",
        area="reliability",
        labels=["reliability", "performance"],
        effort="S",
        evidence_log=[
            '7659a35c — telemetry on the async client, semaphore ops via to_thread, get_running_loop()',
            'tests/test_llm_semaphore.py (token ops never on the loop), tests/test_usage.py',
        ],
        problem=(
            "Per-LLM-call counters and the semaphore release use the synchronous Redis client inline in "
            "async code — exactly the pattern `backend/app/core/security.py` documents as forbidden and correctly "
            "avoids everywhere else."
        ),
        evidence=[
            "`backend/app/graph/clients.py:142-160` `_record_llm_latency` (sync pipeline), called at `:1103` and `:1371` inside the async agent loop; `:163-175` `_record_llm_429`.",
            "`backend/app/graph/usage.py:113-147` `record_token_usage` — sync pipeline per LLM response.",
            "`backend/app/graph/llm_semaphore.py:61-104` `_ensure_tokens` (sync `llen`/`rpush`) from `__aenter__`, and `:106-125,178-181` `__aexit__` sync `rpush`+`llen` — while acquire at `:159` correctly uses `run_in_executor`. The class is internally inconsistent.",
            "Same class elsewhere: `backend/app/services/dashboard/service.py:274-280,304-331` (sync Redis from `async def`), `backend/app/workers/chatbot_worker.py:508-523` (queue-depth read per turn).",
            "Correct pattern already in-repo: `backend/app/core/ops_health.py:12-13`, `backend/app/main.py:270-280`.",
        ],
        impact=(
            "4–12 blocking round trips per turn inside the loop of the process that also serves webhook "
            "acks and inline web-chat turns. Invisible with a healthy local Redis, which is why it "
            "survived review; any Redis latency (RDB fork, memory pressure, AOF fsync) is added "
            "directly to every concurrent request, and a hung Redis blocks the loop until socket "
            "timeout instead of yielding to `asyncio`."
        ),
        fix=(
            "Move the counters and the semaphore release onto the async client "
            "(`app/core/redis.py:get_redis()`) — they are fire-and-forget, so this is a drop-in — or "
            "wrap in `asyncio.to_thread`. Use `asyncio.to_thread` for the dashboard's sync-only reads. "
            "Also replace the deprecated `asyncio.get_event_loop()` at `backend/app/graph/llm_semaphore.py:159` with "
            "`asyncio.get_running_loop()`."
        ),
    ),
    dict(
        id="REL-03",
        column="DEV_COMPLETED",
        title="Redis locks released without an ownership check, with TTLs shorter than the work they guard",
        sev="medium",
        area="reliability",
        labels=["reliability"],
        effort="S",
        evidence_log=[
            '2da7723c (OA lock) + fb344ee0 (reconcile tick lock) — UUID owner, TTL above the guarded work, Lua CAS release',
            'tests/test_zalo_oa_token_refresh.py; tests/test_reconcile_worker.py (_CasRedis)',
        ],
        problem=(
            "Two locks delete their key blindly in `finally`, and one has a TTL that its own worst-case "
            "path exceeds — so a slow holder can delete a successor's lock and admit a third "
            "concurrent holder."
        ),
        evidence=[
            "`backend/app/workers/reconcile_worker.py:132-139` — `SET NX EX=300` then a blind `conn.delete(...)`; the sweep can process `reconcile_batch_size = 50` conversations with a session each (`backend/app/core/config.py:415`).",
            "`backend/app/services/integration_settings.py:812-817` acquires with `nx=True, ex=30` and `:887-897` releases blindly, while the guarded work is two provider POSTs at `zalo_bot_request_timeout = 30` s each plus a DB commit.",
            "Correct patterns already present: `backend/app/core/singleflight.py:123-138` (GETDEL ownership CAS) and `backend/app/services/profile_enrichment.py:160-172`.",
        ],
        impact=(
            "For reconcile this is a load/telemetry defect — duplicate replies are still prevented by "
            "the atomic `acquire_lock`. For the OA token refresh it is a correctness defect: Zalo "
            "refresh tokens are single-use, so two workers redeeming one leaves the loser's stale pair "
            "overwriting the winner's and the OA access token invalid until an admin re-authorizes "
            "(`backend/app/services/integration_settings.py:866` documents this outcome)."
        ),
        fix=(
            "Use `singleflight.release(key, leader_id)` (or an equivalent Lua CAS-delete) for both "
            "locks, storing a UUID as the value, and size the OA refresh TTL above the sum of the "
            "request timeouts it wraps."
        ),
    ),
    dict(
        id="REL-04",
        column="DEV_COMPLETED",
        title="Password-reset OTP is sent by an unreferenced fire-and-forget task",
        sev="medium",
        area="reliability",
        labels=["reliability"],
        effort="S",
        evidence_log=[
            '4f3e609b — module-level task set with done callback for the OTP send',
            'tests/test_password_reset_task_retention.py',
        ],
        problem=(
            "The only code that sends the OTP and writes the email audit rows runs in a task whose "
            "handle is discarded, so it can be garbage-collected or lost on reload — silently."
        ),
        evidence=[
            "`backend/app/services/password_reset_service.py:46-50,118` — `asyncio.create_task(self._send_reset_email(...))`, handle dropped.",
            "`backend/app/services/password_reset_service.py:120-152` — the only sender and the only writer of the `password_reset_email_sent`/`_failed` audit rows.",
            "Contrast in-repo: `backend/app/workers/chatbot_worker.py:16,38-50` and `backend/app/services/conversation/events.py:99-101` both keep a module-level task set with `add_done_callback`.",
        ],
        impact=(
            "The API returns 200 (\"check your email\") while the mail never sends and no failure row is "
            "written — the `except` lives inside the task that never ran — while the OTP row is "
            "already committed. Silent from the operator's side."
        ),
        fix=(
            "Keep a module-level `set[asyncio.Task]` with `add_done_callback`, or use FastAPI "
            "`BackgroundTasks`, or move the send onto the existing `persistence_low` queue where a "
            "failed job surfaces in `rq:failed`."
        ),
    ),
    dict(
        id="REL-05",
        column="DEV_COMPLETED",
        title="leads.gender blank-only guarantee is a read-then-write TOCTOU and the write is unconditional",
        sev="medium",
        area="reliability",
        labels=["reliability"],
        effort="S",
        evidence_log=[
            'ee0e28e5 — blank-only guard moved into the UPDATE (+updated_at, version on override)',
            'tests/test_lead_gender_guard.py (8 tests) — guarded UPDATE, override wins, rowcount semantics',
        ],
        problem=(
            "The \"only fill a blank gender\" rule lives in the adapter as a read-then-write, while the "
            "SQL update itself has no guard — so a concurrent provider enrichment can be overwritten."
        ),
        evidence=[
            "`backend/app/recruitment/infrastructure/service_adapters.py:114-143` — `stored_gender()` reads, then `record_inferred_gender()` re-reads and calls `set_gender_by_id`.",
            "`backend/app/services/lead/repository.py:141-160` — `UPDATE leads SET gender = :gender WHERE id = :lead_id`, no `IS NULL`/blank guard; the docstring at `:142-153` acknowledges the guard lives in the adapter. `version`/`updated_at` are untouched.",
            "The provider path *is* atomic: `backend/app/services/profile_enrichment.py:287-312` uses `.where(..., _blank_column(Lead.gender))`.",
        ],
        impact=(
            "If OA profile enrichment commits `male` between the adapter's read and its write, the blank "
            "guard passes and the inferred value replaces it — the candidate is mis-addressed for the "
            "rest of the conversation, and because `version`/`updated_at` are untouched the recruiter "
            "console cannot show the value changed. With `override=True` it also overwrites a "
            "recruiter's recent CRM edit."
        ),
        fix=(
            "Push the guard into the statement: pass `override` down and add "
            "`or_(Lead.gender.is_(None), func.btrim(Lead.gender) == \"\")` when not overriding, and "
            "bump `updated_at` (plus `version` for the override case) so the console reflects it."
        ),
    ),
    dict(
        id="REL-06",
        column="DEV_COMPLETED",
        title="Outbox PENDING row is dispatcher-visible during the inline send, recording a false ERROR turn",
        sev="medium",
        area="reliability",
        labels=["reliability"],
        effort="S",
        evidence_log=[
            '7e4255b4 — claim_send writes its outbox command already SENDING; dispatch_message_outbox resumes only its own claim',
            'tests/test_outbox.py, tests/test_concurrency.py; integration/test_inline_claim_outbox_visibility.py',
        ],
        problem=(
            "`claim_send` inserts the outbox row as PENDING and only then sends inline, while the 60 s "
            "dispatcher tick selects *all* PENDING rows with no age gate — so the sweep can win the "
            "claim and the turn records an ERROR for a message that was delivered."
        ),
        evidence=[
            "`backend/app/services/conversation/bot_path.py:548-573` — `claim_send` flips the message to SENDING and calls `create_pending_outbox` (row written PENDING) in one transaction.",
            "`backend/app/services/outbox_service.py:710-720` — `pending_outbox_ids()` selects all PENDING rows with no minimum age.",
            "`backend/app/services/outbox_service.py:197-226` — `claim_pending_outbox` is atomic, so **exactly one sender wins and there is no duplicate provider POST**. Verified: do not \"fix\" this.",
            "`backend/app/services/conversation/bot_path.py:684-698` keeps the message SENT via forward-only rank, but `:628-636` still records `BotRunOutcome.ERROR` when `external_error` is set.",
        ],
        impact=(
            "The candidate receives exactly one copy, but the dashboard error tile, the `bot_run` audit "
            "row and the worker log all record a failure — so a later real-failure investigation starts "
            "from false evidence."
        ),
        fix=(
            "Insert the outbox row already in SENDING inside the claim transaction (the stale-SENDING "
            "path terminalizes at-most-once, so this is safe), or add a minimum-age / "
            "`dispatch_claimed_at` gate to `pending_outbox_ids()`."
        ),
    ),
    dict(
        id="REL-07",
        column="DEV_COMPLETED",
        title="Semantic cache scans all vectors in Python on the loop, and its scope guard has a hole",
        sev="medium",
        area="reliability",
        labels=["reliability", "performance"],
        effort="M",
        evidence_log=[
            'c3c70a5a — scope_key(project_ids, top_k), packed float16 vectors, scan via to_thread',
            'tests/test_semantic_cache.py — cross-Page isolation end to end, off-loop scan, corrupt-entry miss',
        ],
        problem=(
            "Every uncached lookup transfers and parses all stored vectors and compares them in pure "
            "Python on the event loop, and the scope guard keys on `project_slug`, which is `None` for "
            "Page-scoped conversations."
        ),
        evidence=[
            "`backend/app/graph/semantic_cache.py:129-148,168-171` — `HGETALL`, `json.loads` per entry, `_cosine` per entry (`:89-102`).",
            "`backend/app/core/config.py:245-248,46` — `semantic_cache_enabled=False`, capacity 200, dim 3072.",
            "`backend/app/graph/tools/knowledge.py:260,309` — the scope guard is `not project_slug`, but a Page-scoped conversation has `project_slug=None` with a non-empty `project_ids` (`backend/app/graph/factories.py:835-860`).",
        ],
        impact=(
            "Dormant today because the feature is off, so this is latent cost plus an enabled-day "
            "correctness hazard: roughly 12 MB transferred and ~600k interpreted float operations per "
            "lookup on a 2 vCPU box, and a cached answer computed against another Page's catalog could "
            "be returned."
        ),
        fix=(
            "Gate on `project_ids is None` rather than `project_slug` (or include the project scope in "
            "the key), store packed float16 with a lower capacity, and run the scan via "
            "`asyncio.to_thread`. If it will not be enabled, delete the call path rather than carrying "
            "an untested branch."
        ),
    ),
]
