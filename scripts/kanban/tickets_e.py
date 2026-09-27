"""Wave-2 tickets: the read-only tech-debt audit of 2026-09-26 (HEAD `31d30377`).

Nine parallel read-only lanes (backend architecture, backend correctness,
backend performance/async, security, graph/bot, frontend, testing/CI,
ops/deploy/dependencies, docs/repo hygiene) over the tree left by the swept
2026-09-24 board. Ids continue each area sequence from wave 1 (allocated once,
never renumbered). Known/deferred wave-1 items were excluded; every claim is
anchored to a `path:line` read at this HEAD.
"""

AUDIT_DATE = "20260926"
AUDIT_HEAD = "31d30377"

TICKETS: list[dict] = [
    # ---------------------------------------------------------------- OPS --
    dict(
        id="OPS-21",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Root Makefile `make backup` fails at HEAD: compose call trips the ${IMAGE_TAG:?} guard",
        sev="high",
        area="ops",
        labels=["ops", "backup", "regression"],
        effort="S",
        problem=(
            "The wave-1 fix for `make backup` (replacing the hardcoded `docker exec "
            "vfic-postgres-1` with `docker compose ps -q postgres`) collided with the OPS-10 "
            "hardening that made IMAGE_TAG a required variable in every app image. On the "
            "droplet, /opt/vfic/.env does not define IMAGE_TAG (prod-env.sh never writes it), so "
            "any compose command without an explicit IMAGE_TAG env fails interpolation. "
            "`docker compose ps -q postgres` therefore errors, PG is empty, and the target "
            "aborts with 'compose reports no postgres container' before any dump is taken."
        ),
        evidence=[
            "Makefile:113-116 — backup's remote step runs `docker compose ps -q postgres` on the droplet with no IMAGE_TAG, then errors `compose reports no postgres container`",
            "backend/docker-compose.yml:103,139,167,212,239,267,297,327,363,441,454 — every app image is `${IMAGE_TAG:?IMAGE_TAG is required — the deploy passes the git sha}`; compose interpolates the whole file for every subcommand, including ps/start/logs",
            "backend/scripts/prod-env.sh:30-99 — the generated /opt/vfic/.env heredoc contains no IMAGE_TAG, so compose auto-load cannot satisfy the guard either",
            "backend/scripts/backup-droplet.sh:42-45 — the repo's own comment: 'The prod compose file requires IMAGE_TAG for EVERY subcommand' — which is why that script resolves the tag from the running container first",
            "Makefile:78 — `deploy-backend: release-check backup`, so the broken backup also blocks the backend-only deploy path",
        ],
        impact=(
            "The documented primary DB backup fails 100% of the time, and `make deploy-backend` "
            "fails with it — DB backups silently stop existing and backend-only deploys are "
            "blocked. Same root cause breaks `make deploy-status` (backend/Makefile:140), all "
            "three `profile-backfill-*` targets (:143-150 — bg_deploy.sh step 9b prints 'Status: "
            "make -C backend profile-backfill-status' after every deploy), and `make adminer` "
            "(:175, masked by `|| true`)."
        ),
        fix=(
            "In the root Makefile backup target, resolve the tag on the droplet before "
            "composing (`docker inspect -f '{{.Config.Image}}'` on the active web container, "
            "then `IMAGE_TAG=$TAG docker compose ps -q postgres` — the pattern backup-droplet.sh:47-67 "
            "already uses). Sweep the sibling no-tag call sites in the same pass: "
            "backend/Makefile:140 (deploy-status), :144 (profile-backfill-run's inner compose ps), "
            ":147/:150 (profile-backfill-status/logs), :175 (adminer)."
        ),
        notes="The wave-1 card (tickets_d.py) recommended the compose call that now breaks — the fix landed without the IMAGE_TAG guard in scope. Differs from the held 'droplet backup/restore rehearsal' and 'bundle-zip pruning' items.",
    ),
    dict(
        id="OPS-22",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="bg_deploy post-flip verification and deploy-breaking service lists omit worker-maintenance and metrics-watch",
        sev="high",
        area="ops",
        labels=["ops", "deploy", "reliability"],
        effort="S",
        problem=(
            "bg_deploy.sh grew WORKERS to include worker-maintenance and metrics-watch (the "
            "2026-09-26 drift fix), but the dependent service lists were not updated. "
            "verify_post_flip_readiness still polls only six services, so worker-maintenance "
            "(which actually pushes bot replies to Zalo) and metrics-watch can sit unhealthy or "
            "crash-looping after the flip while the deploy declares success — recreating the "
            "exact drift class the fix was for, now with no health assertion. Separately, "
            "backend/Makefile deploy-breaking pulls and force-recreates a hardcoded "
            "seven-service list that omits both, so a breaking-migration deploy leaves "
            "old-code workers running against an incompatible schema."
        ),
        evidence=[
            "backend/scripts/bg_deploy.sh:36 — WORKERS=\"worker-chatbot worker-persistence worker-ingest worker-followup scheduler worker-maintenance metrics-watch\" (both added 2026-09-26)",
            "backend/scripts/bg_deploy.sh:245-250 — verify_post_flip_readiness polls require_running_service_count for frontend, worker-chatbot, worker-persistence, worker-ingest, worker-followup, scheduler only",
            "backend/scripts/bg_deploy.sh:340-352 — step 4 force-recreates web-$NEXT plus all NON_TURN_WORKERS from $WORKERS, so both omitted services are already replaced before the flip",
            "backend/scripts/bg_deploy.sh:35-36 — inline comment names worker-maintenance 'the component that actually pushes bot replies to Zalo' and metrics-watch as the queue-depth alert poller",
            "backend/Makefile:161,167 — deploy-breaking pull/up lists: `web-blue worker-chatbot worker-persistence worker-ingest worker-followup scheduler frontend` — no worker-maintenance, no metrics-watch",
        ],
        impact=(
            "A deploy can flip traffic and report success while the outbound dispatcher is "
            "unhealthy or missing — candidates' replies silently stop sending, with deploy gates "
            "green and (metrics-watch down) no in-stack alert firing. On the deploy-breaking "
            "path the outcome is worse by design: stale-code workers run against a schema the "
            "migration just made incompatible with them."
        ),
        fix=(
            "Extend the bg_deploy.sh:245-250 poll loop with require_running_service_count for "
            "worker-maintenance and metrics-watch (bg_rollback.sh's copy of the list too). Add "
            "the two services to backend/Makefile:161 and :167. Pin the invariant with a "
            "repo-level regression test asserting every ${IMAGE_TAG} service from "
            "docker-compose.yml appears in both lists."
        ),
        notes="The known hold covered only the creation gap inside bg_deploy.sh (fixed in WORKERS). These are the lists that did not follow the fix. Land OPS-25 first — both sides of that card touch the same files.",
    ),
    dict(
        id="OPS-23",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="ops-alerts.sh docker checks are dead on arrival (missing IMAGE_TAG, relative ACTIVE_COLOR, unparseable Reclaimable)",
        sev="medium",
        area="ops",
        labels=["ops", "alerting", "regression"],
        effort="S",
        problem=(
            "The sweep grew ops-alerts.sh into the host-side half of the alerting story, but its "
            "two docker-based checks cannot succeed as written. The /metrics probe invokes "
            "`docker compose exec` without IMAGE_TAG, so the `${IMAGE_TAG:?}` guard fails every "
            "subcommand and METRICS is always empty. Colour detection reads `cat ACTIVE_COLOR` "
            "relative to the process cwd — under the documented cron install the cwd is not "
            "/opt/vfic, so it always falls back to blue and would probe the idle colour after a "
            "cutover. The docker-reclaimable check pipes docker's '12.34GB (67%)' text into "
            "`numfmt --from=iec`, which errors into the `|| echo 0` fallback, so the >10GB warn "
            "can never trigger."
        ),
        evidence=[
            "scripts/ops-alerts.sh:57-58 — `docker compose -f /opt/vfic/docker-compose.yml exec -T \"$WEB\" python -c ...` with no IMAGE_TAG in the environment and `|| true` swallowing the failure into empty METRICS",
            "backend/docker-compose.yml:24-27 — header states every compose command fails loudly until IMAGE_TAG is exported, and gives the docker-inspect resolution recipe",
            "scripts/ops-alerts.sh:55 — `COLOR=\"$(cat ACTIVE_COLOR 2>/dev/null || echo blue)\"` reads a relative path; the documented cron invocation at :19 runs from the cron cwd, never /opt/vfic",
            "scripts/ops-alerts.sh:46-48 — `numfmt --from=iec` on '12.34GB (67%)' errors to `|| echo 0`, so the disk warn can never fire",
            "scripts/ops-alerts.sh:19 — install line `* * * * * root /opt/vfic/scripts/ops-alerts.sh`; no Makefile or bg_deploy step ever copies the script to /opt/vfic/scripts (backend/Makefile:110,126 ship only bg_deploy/bg_rollback/flip_caddy)",
        ],
        impact=(
            "The host half of the alerting story reports 'could not read /metrics' (or nothing) "
            "every minute regardless of actual health, and after any green cutover would inspect "
            "the idle colour even if the other bugs were fixed. Permanent noise trains operators "
            "to ignore it — the pre-sweep 'nothing watches' state with extra steps."
        ),
        fix=(
            "`cd /opt/vfic` at the top of the docker section, resolve COLOR from "
            "`cat /opt/vfic/ACTIVE_COLOR`, and resolve IMAGE_TAG from the running container "
            "exactly as backup-droplet.sh:47-67 does, exporting it for the compose exec. Replace "
            "the numfmt parse with `docker system df --format '{{json .}}'` numeric fields (or "
            "strip non-numerics first). Ship the script in the Makefile deploy SCP lists when "
            "the cron wiring hold is picked up."
        ),
        notes="Cron scheduling itself remains the known held item; this card is that the script cannot work even once scheduled. The in-stack metrics-watch service is unaffected.",
    ),
    dict(
        id="OPS-24",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="frontend and caddy services have no healthcheck; the edge is only probed at deploy time",
        sev="low",
        area="ops",
        labels=["ops", "reliability", "observability"],
        effort="S",
        problem=(
            "frontend (nginx SPA) and caddy (the edge) are the only long-running services "
            "without a healthcheck, so their Docker health status is permanently 'none' and "
            "bg_deploy's require_running_service_count can only assert the process exists, not "
            "that it serves. In-stack probing never covers them: metrics-watch polls the web "
            "colours directly on the compose network, and the only edge-level checks are the "
            "deploy-time curl and ops-alerts.sh's public curl — the latter cron-unwired (known "
            "hold) and broken internally (OPS-23)."
        ),
        evidence=[
            "backend/docker-compose.yml:453-460 — frontend service: expose 80, memory limit, restart policy, no healthcheck key",
            "backend/docker-compose.yml:462-480 — caddy service: ports 80/443, Caddyfile mount, no healthcheck key (postgres/redis/web/workers/scheduler all carry one)",
            "backend/docker-compose.yml:362-412 — metrics-watch probes `http://<color>:8000/...` directly, never through caddy",
            "backend/scripts/bg_deploy.sh:224-227 — the only edge probe is deploy-time (`curl https://bot.tingting.vip/health` and `/` during verify_post_flip_readiness)",
        ],
        impact=(
            "A proxy serving 404s/502s or an nginx serving a stale/blank bundle runs "
            "'healthy-looking' indefinitely; detection depends on the currently-nonfunctional "
            "ops-alerts path, so a wedged edge is found by users first."
        ),
        fix=(
            "Add `healthcheck` to frontend: `CMD wget -q --spider http://127.0.0.1/` (nginx "
            "ships wget). For caddy, probe the rendered listener (`wget -q --spider "
            "http://127.0.0.1:80`, accepting the 308) so a wedged edge shows unhealthy in "
            "`docker compose ps` and can gate bg_rollback's service checks."
        ),
        notes="Kept low: static nginx rarely wedges, and caddy failure modes are usually port-level. Complements OPS-23 — together they close the edge-detection gap.",
    ),
    dict(
        id="OPS-25",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Land the uncommitted 2026-09-26 bot-silence remediation (turn_pipeline_check gate + deploy wiring)",
        sev="high",
        area="ops",
        labels=["ops", "incident-followup", "git-hygiene"],
        effort="S",
        problem=(
            "The entire remediation for the 2026-09-26 prod bot-silence incident exists only in "
            "the working tree at the audited HEAD 31d30377: the new post-flip stall gate, its "
            "wiring into both deploy scripts, compose healthcheck budgets, two test files, and "
            "the runbook/deploy-guide sections. A fresh clone, CI, or any deploy built from the "
            "recorded HEAD silently loses the exact guardrail that would have caught the "
            "incident. The remediation report itself flags that the in-container gate needs an "
            "image built from 'this commit' — which does not exist until the set is committed."
        ),
        evidence=[
            "backend/scripts/turn_pipeline_check.py:1-36 — new post-flip gate whose docstring cites the 2026-09-26 incident (83 s worker preload); currently untracked",
            "backend/scripts/bg_deploy.sh:294-298 and backend/scripts/bg_rollback.sh:244-248 — both (tracked) scripts invoke `python -m scripts.turn_pipeline_check` post-flip and abort/roll back on failure",
            "backend/tests/test_turn_pipeline_check.py:17 and backend/tests/integration/test_turn_pipeline_check.py:29 — both untracked test files import `scripts.turn_pipeline_check`",
            "docs/deployment-guide.md:156-158 and docs/incident-runbook.md (modified, uncommitted) — ops docs already instruct operators to run the gate",
            "plans/reports/260926-1325-prod-bot-silence-recovery-completion.md:149-153 — 'the post-flip gate … requires an image built from this commit. Until then the gate would fail-closed on a deploy'",
        ],
        impact=(
            "Next deploy from a clean checkout ships without the stall gate while the deploy "
            "scripts still call it — or a rebuilt image without the file makes every deploy fail "
            "closed; CI's 'green for the exact commit' release guarantee is void for the "
            "remediation. The incident class the gate closes (bot silent, containers healthy, "
            "webhooks 200) becomes undetectable again."
        ),
        fix=(
            "Commit the working-tree remediation set as one change: turn_pipeline_check.py, the "
            "bg_deploy.sh/bg_rollback.sh hunks, backend/docker-compose.yml healthcheck/"
            "start_period budgets, both test files, docs/incident-runbook.md, and the two docs "
            "sections; then cut the next image from that commit so the in-container gate exists "
            "before the next flip. Committing is the only action — the content is already written."
        ),
        notes="Absorbs the sweep-ledger 'worker-maintenance creation gap in bg_deploy.sh' item — the working tree now fixes it. Owner-owned working tree: this card records the landing requirement, it does not authorize an agent to commit unasked.",
    ),
    dict(
        id="OPS-26",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Silence the per-message 'webhook accepted while runtime inactive' log until installation activation ships",
        sev="low",
        area="ops",
        labels=["telemetry", "alerting", "log-noise"],
        effort="S",
        problem=(
            "The 2026-09-26 incident diagnosis proved this INFO line fires on every single "
            "inbound message in prod — `InstallationService.resolve_active()` returns None "
            "because the installation tables have never been populated there — so the one log "
            "signal that would distinguish a genuine runtime-authority regression from steady "
            "state is permanently noisy and unusable for alerting. Meanwhile every turn is "
            "enqueued with an empty runtime stamp, so the runtime-authority gate in run_turn has "
            "never executed against production traffic and its failure modes are unobservable."
        ),
        evidence=[
            "backend/app/api/webhooks.py:91-100 — `_runtime_authority_or_inactive` logs INFO 'webhook accepted while runtime inactive channel=%s' whenever resolve_active() is None, then returns None so the turn still enqueues",
            "plans/reports/260926-1325-prod-bot-silence-recovery-completion.md (benign-signal section) — prod installation_state/manifest tables have 0 rows, so the line fires on 100% of traffic and 'must not be treated as a regression'",
            "backend/app/graph/runner.py:1613-1650 — the stale_runtime_authority/missing_runtime_authority gates only run when a turn carries a runtime stamp, which prod turns never do",
        ],
        impact=(
            "Alerting on this line would page on 100% of traffic (cry-wolf), and a real "
            "regression of the installation/authority rollout is invisible behind the noise; the "
            "authority-gate code path accumulates untested-in-prod drift."
        ),
        fix=(
            "Demote the line to DEBUG with a once-per-process summary or counter, and add an "
            "explicit runbook note that it must never alert; separately schedule the "
            "installation-activation rollout so the authority gates start exercising (or delete "
            "the dead gate if the rollout is cancelled)."
        ),
        notes="Incident-report follow-up; complements the (uncommitted, OPS-25) pipeline-consumer blindness the incident exposed.",
    ),
    dict(
        id="OPS-27",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Add base-uri and form-action directives to the Caddy CSP",
        sev="low",
        area="ops",
        labels=["security", "csp", "edge"],
        effort="S",
        problem=(
            "The deployed CSP covers default-src, object-src, frame-ancestors, style-src, "
            "font-src and img-src, but omits base-uri. Per the CSP spec base-uri does NOT fall "
            "back to default-src, so a page without it accepts an injected `<base href>` tag, "
            "which redirects every relative fetch and can defeat same-origin assumptions. "
            "form-action currently falls back to default-src 'self'; making it explicit protects "
            "against a future relaxation of default-src."
        ),
        evidence=[
            "backend/Caddyfile.template:22 — full CSP string has no base-uri and no form-action",
            "backend/Caddyfile.template:6-10 — this template is the single source of the edge config; flip_caddy.sh renders it, so the fix lands in one file",
            "backend/app/main.py:202 — TrustedHostMiddleware with an explicit host list shows host/URL manipulation is already treated as in scope (SEC-06 lineage)",
        ],
        impact=(
            "If any HTML-injection foothold appears (a compromised npm dependency is the "
            "realistic path given the SPA ships inline scripts), an injected `<base>` can "
            "silently reroute same-origin fetches. Zero functional cost to close: no form posts "
            "and no `<base>` usage exist in the SPA today."
        ),
        fix=(
            "Extend the Content-Security-Policy value at Caddyfile.template:22 with "
            "`base-uri 'self'; form-action 'self';` (consider upgrade-insecure-requests), then "
            "redeploy the edge via flip_caddy.sh. No app changes required."
        ),
        notes="Re-verify style-src/img-src in a browser per the SEC-06 residual note before relying on the expanded header as a control.",
    ),
    # ---------------------------------------------------------------- REL --
    dict(
        id="REL-8",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Initialize `candidate` before try in run_proactive_turn so the error path records the outcome and releases the lock",
        sev="medium",
        area="reliability",
        labels=["error-path", "workers", "proactive-followup"],
        effort="S",
        problem=(
            "run_proactive_turn assigns `candidate` only at proactive.py:354 inside the try, but "
            "the finalization after the except block unconditionally reads `candidate`. The "
            "except deliberately converts any in-try exception into `SendOutcome(ok=False)` so "
            "the failure is recorded via record_proactive_outcome — but any exception raised "
            "before line 354 (LLM call, build_system_prompt, last_messages, direct_context."
            "resolve) crashes the finalizer with UnboundLocalError instead."
        ),
        evidence=[
            "backend/app/graph/proactive.py:354 — `candidate = strip_think_reasoning(message)` is the FIRST assignment of `candidate`, deep inside the try block",
            "backend/app/graph/proactive.py:440-442 — `except Exception as exc:` converts any earlier failure into `result = SendOutcome(ok=False, ...)`",
            "backend/app/graph/proactive.py:446-447 — post-except finalization builds `record_kwargs = {\"message\": candidate, ...}` unconditionally → UnboundLocalError when the exception fired before :354",
            "backend/app/graph/proactive.py:457 — `await svc.state.record_proactive_outcome(conv, **record_kwargs)` is therefore never reached on that path",
            "backend/app/services/conversation/bot_outcome.py:174-193 — the per-chat bot lock is cleared inside record_proactive_outcome, so skipping it leaks the lock",
            "backend/app/core/config.py:273 — bot_lock_ttl_seconds: int = 180 (the leak is time-bounded)",
        ],
        impact=(
            "On a transient LLM/provider failure during a proactive nudge, the designed failure "
            "record is lost: the 180s per-chat bot lock is held (blocking the reactive bot path "
            "and the follow-up scan for that conversation), the flushed last_followup_attempt_at "
            "stamp is rolled back at session close, so the conversation stays fully eligible and "
            "the next 30-min tick retries and re-crashes — up to the 48h window. Logs show "
            "UnboundLocalError instead of the provider error."
        ),
        fix=(
            "Initialize `candidate = \"\"` next to `pending_message_id`/`outbox_channel` so the "
            "except-path finalization can always reach record_proactive_outcome, which then "
            "clears the lock and durably records the failure. Add a regression test that raises "
            "inside a fake deps.agent.agent and asserts the lock columns clear and the outcome "
            "is recorded."
        ),
        notes="Same pattern class as REL-04 (already fixed for the email send); this is the sibling gap in the proactive turn finalization.",
    ),
    dict(
        id="REL-9",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Pin ChatOps schedule_followup due_at to Asia/Ho_Chi_Minh morning instead of 09:00 UTC",
        sev="medium",
        area="reliability",
        labels=["timezone", "leads", "dashboard"],
        effort="S",
        problem=(
            "ChatopsService.apply_action's schedule_followup branch hardcodes "
            "`time(hour=9, tzinfo=timezone.utc)` — 16:00 Vietnam time — for the created "
            "FollowUpTask.due_at and lead.next_action_at. The rest of the product treats "
            "follow-up scheduling on the Asia/Ho_Chi_Minh calendar: the dashboard's "
            "FOLLOWUP_TODAY counter explicitly converts due_at and now() to VN local before "
            "comparing dates, with a comment mandating that form."
        ),
        evidence=[
            "backend/app/services/lead/chatops.py:86-89 — `due_at = datetime.combine(datetime.now(timezone.utc).date() + timedelta(days=1), time(hour=9, tzinfo=timezone.utc))`",
            "backend/app/services/dashboard/repository.py:249-256 — _vn_today_predicate converts both sides to 'Asia/Ho_Chi_Minh' server-side, comment: 'No naive Python date math'",
            "backend/app/services/dashboard/repository.py:291-293 — attention_counters uses `vn_today_due = self._vn_today_predicate(\"f.due_at\")` for FOLLOWUP_TODAY",
            "backend/app/models/provenance.py:381 — WorkingHours.timezone default 'Asia/Ho_Chi_Minh' (deployment-local business time)",
        ],
        impact=(
            "A recruiter scheduling a next-morning follow-up from ChatOps gets a task that only "
            "surfaces in FOLLOWUP_TODAY from 16:00 VN — the task appears in the afternoon/evening "
            "and lead.next_action_at displays the same off-hours time. Latent business-logic "
            "timezone bug on a real recruiter path."
        ),
        fix=(
            "Build due_at from ZoneInfo('Asia/Ho_Chi_Minh') (tomorrow 09:00 ICT = 02:00 UTC), "
            "matching the _vn_today_predicate mandate. Add a test asserting a ChatOps-created "
            "followup lands in FOLLOWUP_TODAY on its VN due morning."
        ),
        notes="Cross-ref the Phase 1 dashboard spec Timezone section cited at dashboard/repository.py:251.",
    ),
    dict(
        id="REL-10",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Route ChatOps apply_action lead writes through optimistic_apply like set_stage/assign",
        sev="low",
        area="reliability",
        labels=["concurrency", "leads"],
        effort="S",
        problem=(
            "Every LeadService mutator (set_stage, assign, update with version) goes through "
            "LeadRepository.optimistic_apply, a conditional `UPDATE ... WHERE version = current` "
            "that raises ConflictError on a lost race. The schedule_followup branch of "
            "ChatopsService.apply_action instead mutates lead attributes directly and commits "
            "with no version predicate, so a concurrent stage change or edit is not detected and "
            "two racing actions can both write version = N+1."
        ),
        evidence=[
            "backend/app/services/lead/chatops.py:90-95 — schedule_followup mutates `lead.next_action_at/updated_at/version += 1` as ORM attributes, then plain commit at :107",
            "backend/app/services/lead/service.py:242-246 — set_stage: `optimistic_apply(...)` else ConflictError",
            "backend/app/services/lead/service.py:212-216 — assign uses the same optimistic_apply + ConflictError pattern",
            "backend/app/services/lead/repository.py:154-168 — optimistic_apply is the documented 'optimistic-concurrency update + commit' primitive",
        ],
        impact=(
            "Two concurrent recruiter actions on the same lead (chatops action + stage change) "
            "can both succeed while the version counter stalls or regresses, so a subsequent "
            "legitimate edit is accepted against a stale precondition the system was designed to "
            "reject. Narrow window; silent corruption of the concurrency token rather than data "
            "loss."
        ),
        fix=(
            "Replace the direct mutation with `await self.leads.repo.optimistic_apply(lead.id, "
            "lead.version, next_action_at=due_at, version=lead.version + 1)` and handle "
            "ConflictError like set_stage, or delegate to a LeadService method that does. Fix "
            "together with REL-9 — same function."
        ),
        notes="K-6 (fixed 2026-09-21) was the same invariant bypassed in another handler; this is the remaining site.",
    ),
    dict(
        id="REL-11",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Make rate-limit bucket TTL establishment atomic with the INCR in _enforce_bucket",
        sev="low",
        area="reliability",
        labels=["redis", "availability", "auth"],
        effort="S",
        problem=(
            "_enforce_bucket does `INCR` and then sets the window TTL only when the returned "
            "count is 1. If the process dies or the Redis connection drops between the INCR and "
            "the EXPIRE (or the EXPIRE errors), the bucket key persists with no TTL; every later "
            "request increments past `limit` and gets 429 permanently, because the TTL is never "
            "re-established on subsequent hits."
        ),
        evidence=[
            "backend/app/core/ratelimit.py:44-50 — `count = await redis.incr(key); if count == 1: await redis.expire(key, window); if count > limit: raise HTTPException(429...)` — two round trips, TTL only on first increment",
            "backend/app/core/ratelimit.py:37-41 — callers include login (Argon2) per-IP and per-email buckets",
            "backend/app/core/ratelimit.py:56-62 — production-only: the bug cannot manifest in dev/tests (development returns early)",
        ],
        impact=(
            "Rare but unrecoverable-without-ops availability bug: a production login endpoint "
            "returns 429 to that IP/email until someone manually deletes the Redis key — on the "
            "auth path whose module docstring says 'auth must stay available'."
        ),
        fix=(
            "Use a small Lua script (INCR + EXPIRE when count == 1) or `SET key 1 EX window NX` "
            "+ INCR so the TTL can never be missing; alternatively refresh `expire(key, window)` "
            "on every increment. Add a unit test asserting the key always carries a TTL after "
            "the first increment."
        ),
        notes="Fail-open behavior for Redis-down is correct and was reviewed; this is only the non-atomic TTL establishment. `app/core/ratelimit.py` is a protected path — fixing needs owner approval.",
    ),
    dict(
        id="REL-12",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Stop rebinding sem in MiniMaxAgent.agent so post-tool LLM rounds keep the Redis concurrency cap",
        sev="high",
        area="reliability",
        labels=["reliability", "concurrency", "telemetry"],
        effort="S",
        problem=(
            "In `MiniMaxAgent.agent`, the local `sem` starts as the cross-process Redis LLM "
            "semaphore but is rebound to a fresh in-process `asyncio.Semaphore("
            "parallel_tool_max_concurrency)` inside the multi-tool dispatch branch. Every "
            "subsequent loop iteration acquires the throwaway per-round semaphore instead of the "
            "Redis one, so any LLM round after a parallel tool round runs outside the "
            "deployment-wide concurrency limit and can never fail fast with LLMThrottled. The "
            "system prompt explicitly instructs the model to issue all independent tool calls in "
            "one round, so the rebind path is common."
        ),
        evidence=[
            "backend/app/graph/clients.py:354 — `sem = get_llm_semaphore()` at agent() entry (RedisLlmSemaphore)",
            "backend/app/graph/clients.py:712 — `async with sem:` guards each model call inside the tool loop",
            "backend/app/graph/clients.py:954-958 — `sem = asyncio.Semaphore(get_settings().parallel_tool_max_concurrency)` rebinds the same local for `_bounded` tool dispatch",
            "backend/app/core/config.py:363-364 — `llm_concurrency_limit: int = 8` ('max concurrent LLM calls, deployment-wide') with 1.5 s LLMThrottled fail-fast; :376 — `parallel_tool_max_concurrency: int = 4` (an in-process DB-pool guard)",
            "backend/app/graph/context.py:22-33 — _RUNTIME_RETRIEVAL_RULES instructs 'GỌI TOOL SONG SONG … gọi TẤT CẢ trong cùng một lượt', so multi-tool rounds are encouraged on every agent turn",
            "backend/app/graph/llm_semaphore.py:14-19 — the Redis semaphore exists precisely because each RQ job gets a fresh event loop",
        ],
        impact=(
            "After any multi-tool round, later rounds of the same turn bypass the 8-token "
            "deployment-wide LLM protection (extra 429s under load), lose the fail-fast that "
            "converts saturation into a clean suppressed turn (they can hang until the 60 s RQ "
            "job timeout), and `llm_queue_ms`/`llm_model_ms` record tool-semaphore waits "
            "(~always 0) — the queue-vs-model latency split goes blind exactly on tool-heavy "
            "turns."
        ),
        fix=(
            "Rename the tool-dispatch semaphore (e.g. `tool_sem` at :954) and use it only inside "
            "`_bounded`; inside the loop, replace the bare `async with sem:` at :712 with "
            "`async with get_llm_semaphore():` so every round reacquires the Redis semaphore."
        ),
        notes="The faq_detail prefetch path already uses a separate name (`sem_pf`, clients.py:535) — the collision is only with the dispatch semaphore.",
    ),
    dict(
        id="REL-13",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Terminalize the progressive early bubble when the lane fails instead of overwriting it with reply=''",
        sev="high",
        area="reliability",
        labels=["reliability", "progressive-send", "state-machine"],
        effort="M",
        problem=(
            "When progressive send claims and dispatches the first bubble mid-generation, the "
            "bubble's message row is flipped SENDING with the real text stamped into `body` and "
            "its outbox command written already-SENDING. Only the success path "
            "(_complete_progressive_prefix) terminalizes that pair. If the lane then fails — "
            "agent exception, LLMThrottled after all providers die mid-stream, or the RQ 60 s "
            "job timeout — every failure terminal records the turn as 'nothing was sent' against "
            "the SAME pending_message_id: record_bot_outcome matches the SENDING row and "
            "overwrites `body` with \"\", and the delivery-rank tie lets the new status win. The "
            "candidate keeps a cut-off answer while the audit row lies."
        ),
        evidence=[
            "backend/app/graph/runner.py:1186-1220 — _await_first_bubble claims with `pending_message_id=state.pending_message_id` and dispatches the bubble; only _complete_progressive_prefix later finalizes it",
            "backend/app/graph/runner.py:905-928 — _record_silent_terminal records reply=\"\" ('nothing was sent') with the same `pending_message_id` on agent error",
            "backend/app/graph/runner.py:1055-1067 — LLMThrottled is re-raised for the worker; backend/app/workers/chatbot_worker.py:589-621 then records reply=\"\" against the same pending_message_id",
            "backend/app/services/conversation/send_claim.py:115,:152-163 — claim_send stamps `body = :reply` (the bubble text), sets SENDING, and writes the outbox command already SENDING",
            "backend/app/services/conversation/bot_outcome.py:120-135,:186-196 — the match set includes SENDING, and `pending_msg.body = reply` plus the delivery-rank tie (app/conversation_messaging/domain/delivery.py:19-29: SENDING=SUPPRESSED=PENDING=0) let the failure status and empty body win",
            "backend/app/workers/chatbot_worker.py:430-478 — _record_abandoned_turn writes `delivery_status=PENDING` with reply=\"\"; repository.py:614 shows PENDING/SENDING/FAILED BOT rows are the sweep's re-enqueue candidates",
        ],
        impact=(
            "On the prod-enabled progressive path (deployed with prod proof in 684bd3ef), any "
            "mid-stream provider death or 60 s overrun leaves the candidate with a truncated "
            "answer, the console showing an empty suppressed message, a SEND_UNKNOWN outbox row, "
            "and — in the timeout variant — a likely duplicate answer once the sweep re-enqueues. "
            "Dashboards undercount sent replies and cannot correlate the delivered bubble with "
            "the turn."
        ),
        fix=(
            "Record the delivered bubble on BotRunState when _await_first_bubble claims it; in "
            "_record_silent_terminal, the worker's LLMThrottled handler, and "
            "_record_abandoned_turn, first finalize_outbound_dispatch the early outbox row, then "
            "record the outcome with the bubble text as reply and sent=send_result.ok, so "
            "record_bot_outcome stops blanking a delivered row."
        ),
        notes="Pairs with TEST-21 (smoke gate would have caught it). The bubble claim touches the shared AsyncSession while the lane streams; lane DB work completes before streaming starts, so no corruption was observed — fragile sequencing worth knowing when editing.",
    ),
    dict(
        id="REL-14",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="De-duplicate the fallback re-emission in _llm_call_streaming_with_retry before shipping the remainder",
        sev="medium",
        area="reliability",
        labels=["progressive-send", "failover", "ux"],
        effort="M",
        problem=(
            "On a mid-stream capacity failure, streaming failover re-runs the full completion on "
            "the next provider, so `stream.raw` becomes dead-provider-prefix + full-fallback-"
            "text. _complete_progressive_prefix knowingly ships `raw[offset:]` as the remainder "
            "— the tail of the dead provider's answer followed by the fallback's full answer — "
            "after the early bubble already delivered the head. The code only logs a "
            "progressive_stream_mismatch warning; nothing de-duplicates the re-emitted prefix "
            "and nothing alarms on the flag, so the candidate can read the same opening content "
            "twice whenever a provider dies mid-stream under progressive delivery."
        ),
        evidence=[
            "backend/app/graph/provider_failover.py:246-301 — _llm_call_streaming_with_retry marks `emitted_before_failover` ('no later attempt can recall') but _failover_stream re-streams the same `messages` on the next provider, only setting metrics['stream_partial']",
            "backend/app/graph/runner.py:1382-1393 — `if full_text != raw_stream:` sets `timings['progressive_stream_mismatch'] = True` and logs a warning; the remainder split still uses the contaminated stream.raw",
            "backend/app/graph/runner.py:1426-1430 — `return ground_reply(remainder_raw, …)` ships the duplicated remainder through the normal claim/dispatch path",
            "backend/tests/test_llm_failover.py:415-433 — the mid-stream failure test uses a no-op on_delta and pins only the stream_partial flag; no test covers the cumulative delta stream or the runner-level duplicated remainder",
        ],
        impact=(
            "Duplicated, contradictory text in the candidate's chat on every mid-stream provider "
            "switch under progressive delivery (prod-enabled); the mismatch frequency is recorded "
            "in stage_timings but is not alarmable, so the defect's real-world rate is invisible."
        ),
        fix=(
            "In provider_failover.py, when `emitted_before_failover` is true, suppress on_delta "
            "for the fallback's re-emitted prefix (detect overlap against the already-emitted "
            "text) or stop streaming and let the caller send only the fallback's full message as "
            "the remainder; in runner.py, alarm/dashboard on progressive_stream_mismatch instead "
            "of a silent warning."
        ),
        notes="The non-progressive path is unaffected (on_delta is only wired when a stream exists).",
    ),
    dict(
        id="REL-15",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Replace the messages[-1].content exhaustion fallback in MiniMaxAgent.agent with an unavailable reply",
        sev="low",
        area="reliability",
        labels=["correctness", "agent-loop"],
        effort="S",
        problem=(
            "If the tool loop exhausts `max_iters` without ever producing a text round (a model "
            "stuck re-requesting tools), `answer_parts` is empty and the tail falls back to "
            "`messages[-1].content` — which after a tool round is the raw ToolMessage payload "
            "(an ACTIVE_JOB_LOOKUP_JSON dump or KB chunk). ground_reply passes it through "
            "because any job IDs in tool output are by definition in the surfaced set, so the "
            "raw tool text ships to the candidate."
        ),
        evidence=[
            "backend/app/graph/clients.py:1040-1053 — `if answer_parts: … else: final = messages[-1].content …` then `return _ground_reply(final, tool_results, …)`",
            "backend/app/graph/grounding.py:403-437 — ground_reply returns the reply unchanged when cited IDs are all in the surfaced set, so tool-output text passes validation",
            "backend/app/graph/clients.py:338 — max_iters defaults to settings.max_llm_calls_per_turn (6, config.py:366-368), all spendable on tool rounds",
        ],
        impact=(
            "Rare but candidate-visible: a raw JSON/KB dump delivered as the bot's answer; it "
            "also pollutes the decision trace with a 'final' round that is actually tool output."
        ),
        fix=(
            "In the `else` branch at clients.py:1046, return the lane's neutral unavailable text "
            "(e.g. VACANCY_LOOKUP_UNAVAILABLE_REPLY for vacancy turns, otherwise a generic "
            "Vietnamese 'chưa thể kiểm tra' line) instead of messages[-1].content, and record a "
            "degradation_reason on the trace."
        ),
        notes="Adjacent to the 37b7cf54 completion work; the continuation path itself is well tested (tests/test_answer_completion_guard.py).",
    ),
    # ----------------------------------------------------------- SECURITY --
    dict(
        id="SEC-9",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Reinstate a deterministic output guard at _finalize_user_visible_reply before candidate sends",
        sev="medium",
        area="security",
        labels=["llm-safety", "candidate-facing", "progressive-send"],
        effort="M",
        problem=(
            "The post-generation content boundary that used to sit between the model and the "
            "candidate was removed outright: runner.py:13-17 documents that the answer-review "
            "layer (regex cleaning, truncation, empty-reply verdicts, safety_verdict trace) and "
            "the LLM safety judge are gone. What remains is strip_think_reasoning (provider "
            "reasoning tags only) plus ground_reply, which validates solely that cited job ids "
            "and entity assertions match tool evidence; all other content passes through "
            "unchanged. The window widened this week: the progressive path dispatches the first "
            "bubble mid-generation, before any later review could exist."
        ),
        evidence=[
            "backend/app/graph/runner.py:13-17 — module docstring states the former answer-review layer and LLM safety judge were removed outright between generation and send",
            "backend/app/graph/runner.py:694-706 — _finalize_user_visible_reply, the converged reply boundary, returns strip_think_reasoning(raw) and nothing else",
            "backend/app/graph/runner.py:1408-1412 — the progressive first bubble is exactly ground_reply(visible_bubble, stream.evidence) wrapped in _finalize_user_visible_reply, then sent",
            "backend/app/graph/grounding.py:392-427 — ground_reply only cross-checks cited job ids and entity assertions; all other content passes through untouched",
            "backend/app/graph/runner.py:2061-2066 — the finalize comment still claims 'Generated replies receive the full safety policy' — stale after the removal",
            "backend/app/graph/types.py:161-167 — progressive_send is an admin-managed flag; when on, the first bubble reaches the candidate mid-generation",
        ],
        impact=(
            "A prompt-injected candidate message or a derailing model completion reaches "
            "candidates verbatim on a live revenue channel: offensive or off-policy text, staff "
            "phone numbers/emails echoed from KB content, or competitor solicitation pass with "
            "no filter. Recruiters cannot intervene in BOT-mode conversations, so nothing "
            "catches it before the candidate reads it."
        ),
        fix=(
            "Decision card — the removal looks deliberate (doc-aligned in 8e90001), so the first "
            "step is an explicit owner risk-acceptance or reinstate decision. If reinstating: a "
            "cheap deterministic guard inside _finalize_user_visible_reply (Vietnamese/English "
            "blocklist term scan, PII regex mask for VN phone/email/long digit runs, hard length "
            "ceiling — all non-model), verdict recorded in the decision trace (reuse the retired "
            "safety_verdict vocabulary, app/schemas/bot_run.py:137-139), one unit test per "
            "guard. Note: touching bot safety behavior is approval-gated per AGENTS.md."
        ),
        notes="Materially new since wave 1: progressive streaming shipped 2026-09-26 (315c4fc, 531901c, 684bd3e, 38ad9d6). Deliberately severity medium pending the owner decision rather than presuming the removal was a mistake.",
    ),
    dict(
        id="SEC-10",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Bound admin multipart reads before the 20 MiB check in knowledge.py and personas.py upload routes",
        sev="low",
        area="security",
        labels=["security", "uploads", "hardening"],
        effort="S",
        problem=(
            "Three admin multipart upload routes call `await file.read()` on the full request "
            "body before enforcing MAX_UPLOAD_BYTES = 20 MiB. Starlette spools bodies over "
            "~1 MiB to a temp file, but .read() pulls the entire body into RAM in one allocation "
            "before the cap check runs. The SEC-05 lesson already produced the right patterns "
            "elsewhere — webhooks.py checks Content-Length before reading, and projects.py:316 "
            "does a bounded read — but knowledge.py and personas.py never got them. Caddy sets "
            "no request_body limit either, so nothing upstream bounds the body."
        ),
        evidence=[
            "backend/app/api/knowledge.py:170-171 — upload_kb_version_file does `data = await file.read()` before _reject_oversized_upload(data)",
            "backend/app/api/knowledge.py:396-397 — upload_file (documents/upload-file) repeats the unbounded read-then-check",
            "backend/app/api/personas.py:166-170 — import_persona reads fully then assert_upload_size(len(data)); the comment claims it prevents buffering, but the read already completed",
            "backend/app/api/projects.py:316-317 — the correct pattern: `raw = await file.read(500_001)` bounded read before the size check",
            "backend/app/api/webhooks.py:83-103 — _read_body_within_limit checks Content-Length before request.body(); never applied to the upload routes",
            "backend/docker-compose.yml:116,149 — web-blue/web-green memory limits 384M are the only backstop for the active web color",
        ],
        impact=(
            "An admin account (or a hijacked admin session) can OOM-kill the active web color "
            "mid-request: latency spikes for every user, blue/green has no automatic flip on "
            "OOM, and repeated posts can fill the droplet disk via spool files. Bounded by the "
            "admin-only gate — hence low — but the fix is three one-line edits."
        ),
        fix=(
            "Replace `await file.read()` with `await file.read(MAX_UPLOAD_BYTES + 1)` at "
            "knowledge.py:170 and :396 and personas.py:166 (mirroring projects.py:316), "
            "optionally hoisting a Content-Length precheck like webhooks.py:87-96. Extract the "
            "shared _reject_oversized_upload helper to app/services/ingestion/limits.py so "
            "personas.py reuses it."
        ),
        notes="api/ routes are transport surface — allowed to edit without extra approval, but verify the three routes' error contracts stay identical.",
    ),
    dict(
        id="SEC-11",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Redis credentials passed as process arguments in four compose services and the redis healthcheck",
        sev="low",
        area="security",
        labels=["security", "ops", "hygiene"],
        effort="S",
        problem=(
            "REDIS_URL embeds the Redis password, and four services pass it as a command-line "
            "argument instead of the environment. Command lines are world-readable inside the "
            "container via /proc and are shown in full by `docker ps`/`docker inspect` on the "
            "host. worker-chatbot and worker-persistence in the same file demonstrate the "
            "intended pattern: read REDIS_URL from env_file. The redis healthcheck likewise "
            "embeds ${REDIS_PASSWORD} as an argv, duplicated into every container's inspect "
            "output."
        ),
        evidence=[
            "backend/docker-compose.yml:248 — worker-ingest `command: [\"rq\", \"worker\", \"ingest\", \"--url\", \"${REDIS_URL}\"]`",
            "backend/docker-compose.yml:271 — scheduler `command: [\"rqscheduler\", \"--url\", \"${REDIS_URL}\"]`",
            "backend/docker-compose.yml:305,335 — worker-followup and worker-maintenance repeat the `--url ${REDIS_URL}` pattern",
            "backend/docker-compose.yml:167-175 — worker-chatbot's command reads REDIS_URL from env_file instead; worker-persistence (:212+) does the same",
            "backend/docker-compose.yml:73-77 — redis healthcheck embeds `-a ${REDIS_PASSWORD}` in the inspectable command (redis-cli prints an -a warning on every probe)",
        ],
        impact=(
            "Anyone with docker visibility (or any process inside those containers) reads the "
            "production Redis password in plaintext from ps/proc despite the .env being mode "
            "600. Consistent env-based handling also removes the two-conventions maintenance "
            "hazard."
        ),
        fix=(
            "Drop `--url ${REDIS_URL}` from the four commands — rq and rqscheduler default to "
            "the REDIS_URL environment variable, which env_file already provides. For the redis "
            "healthcheck, pass REDISCLI_AUTH via the service environment and use "
            "`redis-cli ping` (or accept --no-auth-warning). Verify with `docker inspect` that "
            "no credential appears in Args/Env of healthcheck definitions. Compose is a "
            "deployment file — approval-gated per AGENTS.md."
        ),
        notes="Requires host/container-level access to exploit, hence low; carded because REDIS_PASSWORD handling was an explicit audit item and the safe pattern already exists in the same file.",
    ),
    # ------------------------------------------------------------ PERF --
    dict(
        id="PERF-15",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Cut webhook ack path to one column-scoped conversation refresh",
        sev="medium",
        area="performance",
        labels=["performance", "database", "hot-path"],
        effort="S",
        problem=(
            "ZaloWebhookService.handle performs three full-session `db.refresh(conv)` calls per "
            "inbound message. Conversation.contact and .channel_identity are lazy=\"selectin\", "
            "so each refresh re-fetches the row plus both relationship rows — ~9 SELECTs total — "
            "when at most one column-scoped refresh after record_inbound is needed to observe a "
            "concurrent recruiter takeover. runner.py:85-102 documents this exact cost and "
            "already fixed the turn path with _OWNERSHIP_REFRESH_COLUMNS; the webhook path never "
            "got the same treatment. The two `svc.get(conv.id)` calls before refreshes are "
            "identity-map hits that add nothing."
        ),
        evidence=[
            "backend/app/services/webhook.py:125-126 — `conv = await svc.ensure(...)` immediately followed by full `await db.refresh(conv)`",
            "backend/app/services/webhook.py:139-140 — second reload: `svc.get(conv.id)` (identity-map hit) + another full `db.refresh(conv)`",
            "backend/app/services/webhook.py:195-196 — third reload after persist_explicit_name: same pair again",
            "backend/app/models/conversation.py:122-125 — Conversation.contact and .channel_identity are lazy=\"selectin\", so every full refresh re-fetches both rows",
            "backend/app/graph/runner.py:85-102 — the repo's own measurement: 'A full db.refresh(conv) also re-fetches the contact and channel_identity selectin relationships — 3–4 extra SELECTs per refresh'; fixed on the turn path with _OWNERSHIP_REFRESH_COLUMNS",
        ],
        impact=(
            "Every inbound candidate message pays ~9 avoidable SELECTs on the <1s-ack path that "
            "also stamps webhook_ack_ms — exactly the cost the repo measured and eliminated on "
            "the turn path but not on ingress."
        ),
        fix=(
            "Replace the three refreshes with one column-scoped refresh after record_inbound "
            "using the runner.py pattern: reload only the columns the guards read (mode, status, "
            "version, taken_over_at, assigned_recruiter_id, updated_at, bot_locked_until/"
            "bot_lock_owner) — e.g. a shared _GUARD_REFRESH_COLUMNS or a "
            "ConversationService.reload_guards(conv) helper — and delete the two redundant "
            "svc.get(conv.id) identity hits. Keep the pre-acquire_lock refresh so the takeover "
            "race guard stays correct."
        ),
        notes="The same full-refresh pattern is intentional (error-path-only) at runner.py:865,1695,1709 — leave those; only webhook ingress needs the cutover.",
    ),
    dict(
        id="PERF-16",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Cache persistence-worker extractor and embedder clients across jobs",
        sev="low",
        area="performance",
        labels=["workers", "http-clients"],
        effort="S",
        problem=(
            "worker-persistence builds its extractor and embedder from scratch on every job, and "
            "both construct new langchain ChatOpenAI / httpx-backed client instances each time. "
            "The chatbot worker deliberately caches these process-wide (client_cache + "
            "warm_llm_client_cache) with measured multi-second cold-construction cost; the "
            "persistence queue — one job per SENT bot reply — pays a fresh construction plus "
            "fresh TLS handshake for every reply, contradicting the same client-reuse directive "
            "it sits next to."
        ),
        evidence=[
            "backend/app/workers/persistence_worker.py:84-90 — _build_extractor() → build_minimax_extractor() runs inside _persist_candidate_async, once per job",
            "backend/app/workers/persistence_worker.py:96-102 — build_embedder(openrouter_api_key=...).batch also constructed per job",
            "backend/app/graph/factories.py:37-44 — build_minimax_extractor calls _chat_for_role, constructing a new provider client per invocation",
            "backend/app/graph/clients.py:1174-1188 — _minimax_chat builds a fresh ChatOpenAI per call; langchain_openai creates its own httpx pool per instance",
            "backend/app/graph/client_cache.py:16-23 and backend/app/workers/chatbot_worker.py:222-260 — the chatbot worker warms _client_cache once per process because client construction measured ~5-7s cold",
        ],
        impact=(
            "One-plus fresh TLS handshakes and client constructions per sent reply on a queue "
            "sharing the same droplet; added per-job latency and socket churn, and a standing "
            "exception to the documented client-reuse directive the next worker will copy."
        ),
        fix=(
            "Extend graph/client_cache.py with a lazily-built extractor bundle (or expose the "
            "cached embedder from _build_cached_clients) and have _persist_candidate_async take "
            "clients from the cache instead of calling _build_extractor()/build_embedder() per "
            "job; aclose_client_cache already tears the bundle down process-wide at shutdown "
            "(async_runner.py shutdown_resources), so lifecycle needs no new handling."
        ),
        notes="The same build-per-job shape exists in make_minimax_llm_json for the ingest worker (factories.py:47-70) and can adopt the same fix in the same change.",
    ),
    dict(
        id="PERF-17",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Migration 0055's halfvec match_memories overload is never called — memories retrieval still brute-forces via the vector overload",
        sev="medium",
        area="performance",
        labels=["database", "performance", "migration"],
        effort="S",
        problem=(
            "0055's stated goal is making the memories HNSW halfvec index usable, but it only "
            "CREATE OR REPLACEs the SQL function with a halfvec(3072) first argument. In "
            "Postgres, functions are identified by name + argument types, so this adds a second "
            "overload; the original vector-typed function stays in every environment. The sole "
            "caller passes CAST(:emb AS vector), which resolves exactly to the legacy overload, "
            "whose body orders by `embedding <=> query_embedding` on plain vector — unable to "
            "use the halfvec HNSW index built by 0016. 0016's own docstring says the index stays "
            "unusable until the query casts to halfvec; that follow-up is still incomplete after "
            "0055. The 0055 docstring's reversibility claim ('CREATE OR REPLACE swaps "
            "signatures in place') is not Postgres semantics — the downgrade re-creates the "
            "vector form but never drops the halfvec overload."
        ),
        evidence=[
            "backend/app/services/retrieval/document_repository.py:167-170 — `SELECT content, similarity FROM match_memories(CAST(:emb AS vector), :k, CAST(:filter AS jsonb))` — the vector argument binds to the vector overload",
            "backend/alembic/versions/0016_query_perf_indexes.py:6-13 — docstring: pgvector 'will not use the HNSW index until a follow-up adds embedding::halfvec(3072) <=> ...' to the memories query",
            "backend/alembic/versions/0055_memories_match_halfvec.py:36 — upgrade creates `match_memories(query_embedding halfvec(3072), ...)`; a different-arg-type CREATE OR REPLACE adds an overload, it cannot replace the vector-typed function",
            "backend/alembic/versions/0055_memories_match_halfvec.py:14-16 and ~:61-75 — the 'reversible, swaps signatures in place' claim vs a downgrade that leaves the halfvec overload behind",
            "backend/app/graph/memory.py:46-47 — match_memories is the per-turn memory-recall path (search_user_memory tool), so every turn pays the seq-scan cost",
        ],
        impact=(
            "The memories HNSW index (0016) remains dead weight and memory recall runs exact "
            "sequential scans per turn — the deferred-perf state 0016 explicitly documents, "
            "unchanged by 0055. Environments also keep a stale extra function after downgrade, "
            "contradicting the migration's own reversibility claim."
        ),
        fix=(
            "Change document_repository.py:168-169 to cast the query as halfvec — "
            "`CAST(:emb AS halfvec(3072))` — mirroring the knowledge_chunks path in the same "
            "file, and add an EXPLAIN-based test that memories_embedding_halfvec_hnsw_idx is "
            "used. Then `DROP FUNCTION IF EXISTS public.match_memories(vector, integer, jsonb)` "
            "in 0055's upgrade (or a 0056) with a matching DROP in the downgrade, and correct "
            "the docstring. Postgres resolves exact-type matches over implicit casts, so this "
            "cannot regress once the old overload is dropped. Migration edits are approval-gated."
        ),
        notes="Fresh installs have the same shape (0001 baseline vector form + 0016 halfvec index + 0055 halfvec overload), so the caller fix is required everywhere, not just prod.",
    ),
    # ------------------------------------------------------------ ARCH --
    dict(
        id="ARCH-20",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Split graph/runner.py: 2153-LOC turn orchestrator mixes 7 responsibilities",
        sev="high",
        area="architecture",
        labels=["god-module", "chat-hot-path"],
        effort="L",
        problem=(
            "graph/runner.py is a single 2153-line module that owns every stage of a bot turn: "
            "progressive streaming/early bubbles, outbox claim+dispatch, lane routing, authority "
            "gating, telemetry stamping, typing heartbeat, and the run_turn entrypoint. Any "
            "change to any stage edits the same file, and the module is on the chat hot path "
            "(imported by workers/chatbot_worker and the webhook flow), making it the "
            "highest-conflict file in the churned backend. The stage functions already "
            "communicate through narrow parameters, so they split cleanly along existing seams."
        ),
        evidence=[
            "backend/app/graph/runner.py:190 — _ProgressiveStream + _EarlyBubble (:212) + _next_sendable_offset (:139) + _await_first_bubble (:1337) + _complete_progressive_prefix (:1476) implement progressive bubble delivery inline",
            "backend/app/graph/runner.py:277 — _build_outbox_payload/_dispatch_claimed_message (:292)/_claim_and_dispatch (:1156)/_record_dispatched_outcome (:1240) implement claim+dispatch of the durable outbound command",
            "backend/app/graph/runner.py:362 — _agent_turn (:362-665), _direct_context_turn (:667), run_manifest_composed_agent (:709), _resolve_lane (:993) and the vacancy/income arg builders (:913-975) implement lane routing",
            "backend/app/graph/runner.py:824 — _authority_gate plus _record_silent_terminal (:786) implement ownership stand-down and outcome recording",
            "backend/app/graph/runner.py:754 — _status_heartbeat/_cancel_status_task implement channel typing UX; :322/:329/:894 implement timing/telemetry stamping",
            "backend/app/graph/runner.py:1590 — run_turn is the 560+ line end-to-end entrypoint tying all of the above together (file total 2153 lines)",
        ],
        impact=(
            "Every turn-level feature lands in one file reviewers must re-read in full; the "
            "seven concerns cannot be unit-scoped without importing the whole orchestrator, and "
            "merge conflicts concentrate on the hottest file in the backend."
        ),
        fix=(
            "Extract along the existing seams into graph/ modules: progressive.py "
            "(_ProgressiveStream, _EarlyBubble, _next_sendable_offset, _await_first_bubble, "
            "_complete_progressive_prefix), dispatch.py (_build_outbox_payload, "
            "_dispatch_claimed_message, _claim_and_dispatch, _record_dispatched_outcome), "
            "lanes.py (_agent_turn, _direct_context_turn, _resolve_lane, route arg builders), "
            "authority.py (_authority_gate, _record_silent_terminal), telemetry.py (_stamp_* "
            "helpers), keeping run_turn in runner.py as the composition point. No behavior "
            "change; tests keep passing against re-exports during the move."
        ),
        notes="REL-13/REL-14 and SEC-9 all edit this file — land the behavior cards or this split first, not both in the same window.",
    ),
    dict(
        id="ARCH-21",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Extract MiniMaxAgent.agent: 719-line method inside 1481-LOC graph/clients.py",
        sev="high",
        area="architecture",
        labels=["god-module", "chat-hot-path"],
        effort="L",
        problem=(
            "graph/clients.py mixes four concerns: embedding clients, cut-answer text surgery, "
            "the MiniMaxAgent generation loop, and provider chat-model constructors. The core "
            "defect is MiniMaxAgent.agent, a single ~719-line method that inlines route "
            "prefetch, tool binding, tool dispatch, retry/failover, streaming, metrics, and "
            "answer finalization. Every provider-behavior change edits it."
        ),
        evidence=[
            "backend/app/graph/clients.py:291 — class MiniMaxAgent; agent() starts at :322 and the next method direct() starts at :1042, making agent ≈719 lines (file total 1481)",
            "backend/app/graph/clients.py:60 — GeminiEmbedder (:60), OpenRouterEmbedder (:112), build_embedder (:177) — embedding transport lives in the same module as the generation loop",
            "backend/app/graph/clients.py:226 — cut-answer surgery helpers _answer_was_cut/_should_continue_cut_answer/_join_answer_parts/_seam_remainder/_drop_dangling_tail (:226-289)",
            "backend/app/graph/clients.py:1174 — provider chat constructors _minimax_chat (:1174), _custom_chat (:1233), _openrouter_chat (:1285), _active_llm_provider (:1336), _chat_for_role (:1370)",
            "backend/app/graph/runner.py:362 — runner._agent_turn must pass 10+ kwargs (required_tool, required_tool_args, on_delta, on_evidence, resolved_tool_registry, …) into this one method, evidence of the collapsed abstraction",
        ],
        impact=(
            "The tool-loop invariants (prefetch vs required_tool guards, empty-retry, answer "
            "continuation, failover binding) are unverifiable by inspection; a misplaced edit to "
            "one concern silently changes turn behavior for every lane, and the module cannot be "
            "tested without stubbing all four concerns at once."
        ),
        fix=(
            "Move embedders + build_embedder to graph/embedders.py, the cut-answer helpers to "
            "graph/answer_repair.py, and the _*_chat/_chat_for_role constructors to "
            "graph/providers.py (tests monkeypatch these constructors — keep the module path "
            "stable or update patch targets in one commit). Then decompose MiniMaxAgent.agent "
            "into private phases on the existing local state (prefetch_routes(), "
            "_run_generation_round(), _finalize_answer()), keeping agent as a thin orchestrator "
            "so ports and tests keep their contract."
        ),
        notes="REL-12/REL-15 edit inside agent() — sequence with this split. Companion to ARCH-20; both are the two files >1000 LOC in backend/app.",
    ),
    dict(
        id="ARCH-22",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Consolidate the three diverged knowledge-upload extraction paths in knowledge/service.py",
        sev="medium",
        area="architecture",
        labels=["duplication", "knowledge"],
        effort="M",
        problem=(
            "Uploading a knowledge file has three near-identical extract wrappers and two format "
            "detectors that already disagree. file_extraction.py owns the permissive detector "
            "plus extract_text; knowledge/service.py re-implements a stricter detector and its "
            "own docx/utf-8 dispatcher for the KB-version path (raising ValueError, with error "
            "text that even omits .docx although it is accepted), and a third static wrapper "
            "serves the legacy upload path. The legacy path accepts csv/json suffixes the "
            "KB-version path rejects, so identical files behave differently by endpoint."
        ),
        evidence=[
            "backend/app/services/knowledge/file_extraction.py:21 — _detect_upload_format returns any suffix/'binary' permissively; extract_text (:87-102) dispatches docx/xlsx/utf-8 and raises KnowledgeFileExtractionError",
            "backend/app/services/knowledge/service.py:677 — _detect_upload_text_format is a second detector (docx/markdown/text) raising ValueError('Only .txt and .md knowledge files are supported.') although the docx branch above it is accepted (:680)",
            "backend/app/services/knowledge/service.py:702 — _extract_kb_upload_text re-implements the docx/utf-8 dispatch of extract_text with a different error type",
            "backend/app/services/knowledge/service.py:398 — third wrapper KnowledgeService._extract_upload_text calls _detect_upload_format again and returns a (text, metadata) shape for upload_bytes (:355)",
            "backend/app/api/knowledge.py:173 — KB-version route calls upload_text_file (strict path) while api/knowledge.py:399 legacy route calls upload_bytes (permissive path)",
        ],
        impact=(
            "A format-handling bug must be fixed in up to three places; the same spreadsheet "
            "uploads to the legacy endpoint but is rejected on the KB-version endpoint; divergent "
            "exception types give the two routes different HTTP error contracts."
        ),
        fix=(
            "Keep file_extraction.py as the single owner: extend _detect_upload_format/"
            "extract_text with a strict mode (allowed_formats parameter) so upload_text_file "
            "calls extract_text(strict={docx,markdown,text}) instead of _extract_kb_upload_text; "
            "delete service.py:677-712 module helpers; have _extract_upload_text (:398) delegate "
            "the decode step to extract_text and keep only metadata assembly. Update the two "
            "api/knowledge.py call sites' exception handling in the same change."
        ),
        notes="service.py totals 712 LOC mixing this duplication with versioning, reconciliation and mutability checks.",
    ),
    dict(
        id="ARCH-23",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Split KnowledgeCategoryService (833 LOC): revision CRUD vs cutover/rollback vs unit rendering",
        sev="medium",
        area="architecture",
        labels=["god-module", "knowledge"],
        effort="M",
        problem=(
            "services/knowledge/category_service.py is 833 lines and the service class owns four "
            "distinct jobs: category revision staging/activation/clear, category-authority "
            "cutover and rollback with snapshot surgery, cross-category job-reference "
            "validation, and RAG unit rendering. activate_revision alone spans ~198 lines. The "
            "cutover/rollback snapshot logic — the riskiest code, it rewrites project pointers — "
            "is buried between CRUD methods."
        ),
        evidence=[
            "backend/app/services/knowledge/category_service.py:65 — KnowledgeCategoryService spans :65-789 in an 833-line file",
            "backend/app/services/knowledge/category_service.py:306 — activate_revision runs :306-503 (lease, validation, projection rebuild, embed, activate)",
            "backend/app/services/knowledge/category_service.py:563 — cutover_category_authority (:563-635) and rollback_category_authority (:637-698) manually rewrite category pointers, project projection fields and snapshots",
            "backend/app/services/knowledge/category_service.py:741 — _validate_active_job_references cross-checks JOBS ids across sibling category revisions (domain rule inside the service)",
            "backend/app/services/knowledge/category_service.py:791 — module-level _render_units (:791-833) builds embedder input units, a rendering concern unrelated to the transactional service",
        ],
        impact=(
            "Cutover/rollback is the highest-blast-radius knowledge operation and is "
            "unreviewable inside a mixed 833-line module; a regression in rendering or validation "
            "ships coupled to authority-pointer rewrites, and tests must construct the whole "
            "service to exercise one concern."
        ),
        fix=(
            "Extract cutover/rollback (with _require_rag_project/_locked_project/"
            "_locked_category helpers and the snapshot dataclass) into knowledge/"
            "category_authority.py; move _render_units into category_projections.py or the "
            "category definition module it already reads; move _validate_active_job_references "
            "next to validate_job_references in category_contracts.py. Keep "
            "KnowledgeCategoryService delegating so api/knowledge.py call sites are unchanged."
        ),
        notes="The knowledge package is one of the churn-heaviest areas since the wave-1 audit.",
    ),
    dict(
        id="ARCH-24",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Shrink ConversationService union facade living in services/conversation/__init__.py",
        sev="medium",
        area="architecture",
        labels=["leaky-abstraction", "facade"],
        effort="M",
        problem=(
            "The ConversationService facade is defined inside the package __init__.py and "
            "re-exposes the union of ConversationRepository, ConversationState and the event bus "
            "with hand-copied full signatures — 527 lines of mostly one-line delegations. Every "
            "new state/repo method must be manually mirrored here or consumers silently miss it, "
            "and every signature change is edited twice. Importing app.services.conversation "
            "also pulls the entire state machine, which forced the TYPE_CHECKING dance at the "
            "top of the file."
        ),
        evidence=[
            "backend/app/services/conversation/__init__.py:17 — module docstring: facade composing repository/event bus/state, re-exposing the union of public methods; 527 lines",
            "backend/app/services/conversation/__init__.py:150-283 — verified stretch of pure forwarders (ensure_by_identity, record_inbound, acquire_lock, release_lock, renew_lock, recheck_ownership, claim_send, finalize_outbound_dispatch) each duplicating the full parameter list of self.state.*",
            "backend/app/services/conversation/__init__.py:20-24 — runtime imports of the three submodules plus TYPE_CHECKING-only model imports to dodge circulars",
            "backend/app/graph/ports.py:140 — ConversationPort already declares the narrowed surface the graph brain needs, so the wide union serves only api/services callers",
        ],
        impact=(
            "Signature drift between state/repo and the facade is caught only at call time; "
            "contributors adding a ConversationState method must know to touch __init__.py, and "
            "the package's import side effects grow with every facade line."
        ),
        fix=(
            "Move the ConversationService class verbatim to services/conversation/service.py, "
            "leaving __init__.py re-exporting ConversationService/ConversationConflict (one line "
            "each, zero import-behavior change). Then expose the composed parts directly "
            "(service.state / service.repo are public today) and migrate api/conversations.py + "
            "services/webhook.py call sites to the named part they mean, keeping graph consumers "
            "on ConversationPort. Delete forwarders once no caller remains."
        ),
        notes="claim_send is one of the forwarders — it is a verified-atomic seam (README not-tickets); preserve the delegation target exactly.",
    ),
    dict(
        id="ARCH-25",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Split remaining >600-LOC modules: conversation/repository.py, recruiter_path.py, chatbot_worker.py",
        sev="medium",
        area="architecture",
        labels=["god-module", "chat-hot-path"],
        effort="M",
        problem=(
            "Three more files crossed the 600-line threshold with mixed responsibilities. "
            "ConversationRepository (704) mixes CRM inbox reads with the reconcile-sweep SQL "
            "machinery. RecruiterMessagingState (664) stacks takeover lifecycle, recruiter "
            "messaging, delivery receipts, and follow/unfollow in one class. "
            "workers/chatbot_worker.py (658) stacks the direct-ASGI turn bridge, RQ enqueueing, "
            "the crash guard, mid-turn handoff, and timings builders. Each is cohesive enough "
            "to split mechanically along its existing sections."
        ),
        evidence=[
            "backend/app/services/conversation/repository.py:149 — ConversationRepository (704 lines): viewer-scoped CRM reads (list :256, needs_attention_count :346) alongside reconcile SQL (find_reconcile_candidates :536, latest_inbound_never_given_a_turn :661)",
            "backend/app/services/conversation/repository.py:82 — the reconcile SQL block (_MASKED_INBOUND_SQL + find_reconcile_candidates) is ~170 lines of embed-string SQL inside the CRM repository",
            "backend/app/services/conversation/recruiter_path.py:61 — RecruiterMessagingState (664 lines): takeover/release/semi-auto (:77,:134,:194), close/reopen/clear/delete (:252-347), recruiter messaging (:356-519), receipts (:522-618), follow/unfollow (:638-663)",
            "backend/app/workers/chatbot_worker.py:26 — direct-ASGI turn scheduling/bridge (:26-150) vs RQ enqueue (:152,:172) vs crash guard (:389,:471) vs handoff (:325) vs timings builders (:275,:300); 658 lines",
        ],
        impact=(
            "The reconcile sweep, recruiter inbox actions and worker crash recovery are "
            "independently changing concerns that share one file each; reviewers of a CRM query "
            "tweak must diff past the lost-turn SQL, and worker lifecycle changes sit next to "
            "enqueue policy."
        ),
        fix=(
            "Low-risk mechanical moves: (1) split conversation/repository.py into repository.py "
            "(reads) + reconcile_queries.py (the _MASKED_INBOUND_SQL block, "
            "find_reconcile_candidates, latest_inbound_never_given_a_turn — the reuse keeps a "
            "single SQL definition); (2) split recruiter_path.py's messaging/receipt half into "
            "recruiter_receipts.py; (3) split chatbot_worker.py's direct-ASGI bridge into "
            "direct_turn.py and keep enqueue + job entrypoints + crash guard in "
            "chatbot_worker.py. Re-export from the old paths so test import sites stay valid, "
            "then update callers."
        ),
        notes="recruiter_path.py's docstring shows decomposition is already the accepted pattern (state.py/bot_path.py/recruiter_path.py); this finishes it.",
    ),
    dict(
        id="ARCH-26",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Delete orphan Settings.agent_max_seconds and the stale min_llm_time_budget comment",
        sev="low",
        area="architecture",
        labels=["dead-code", "config-sprawl"],
        effort="S",
        problem=(
            "core/config.py keeps agent_max_seconds although its own docstring says the hard cap "
            "was retired and nothing enforces it; the only code reference is a test that sets it "
            "to 0.1s specifically to assert it has no effect — a characterization test of "
            "removed behavior. Immediately below, a dangling comment block still describes a "
            "min_llm_time_budget gating rule for a field that no longer exists anywhere in the "
            "repo. Operators reading Settings can believe an 8.5s agent cap is active when the "
            "agent is deliberately uncapped."
        ),
        evidence=[
            "backend/app/core/config.py:297-300 — 'Retired as a hard cap — the agent is no longer wrapped in asyncio.wait_for…' above agent_max_seconds: float = 8.5",
            "backend/app/core/config.py:351-353 — comment references min_llm_time_budget; repo-wide grep finds no such field or symbol",
            "backend/tests/test_graph_runner_turn.py:1242-1243 — monkeypatches agent_max_seconds=0.1 to pin that the dead knob has no enforcing effect",
            "docs/troubleshooting/chatbot-response-path.html:276 — ops docs still list agent_max_seconds 8.5 as a turn stage",
            "backend/app/core/config.py:276,309 — chat_turn_job_timeout comments cross-reference the retired knob",
        ],
        impact=(
            "A maintainer tuning turn latency can waste time on a knob that does nothing, or "
            "re-'fix' the test that guards nothing; the stale comment misdocuments the deadline "
            "model with a fallback mechanism that no longer exists."
        ),
        fix=(
            "Remove the agent_max_seconds field and both cross-reference comments (config.py:276, "
            ":297-300, :309), delete the orphaned :351-353 comment block, delete the monkeypatch "
            "pair at test_graph_runner_turn.py:1242-1243 (keep the surrounding test), and drop "
            "the table row in docs/troubleshooting/chatbot-response-path.html:276. pydantic-"
            "settings extra='ignore' means any leftover AGENT_MAX_SECONDS env var is silently "
            "ignored after removal. config.py is a protected path — needs owner approval."
        ),
        notes="Related dormant-config cleanup: ARCH-27 removes the FAQ-bypass flag.",
    ),
    dict(
        id="ARCH-27",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Remove the disabled FAQ-bypass lane: dead adapter wiring, orphan config flag, phantom dashboard taxonomy",
        sev="low",
        area="architecture",
        labels=["dead-code", "observability"],
        effort="M",
        problem=(
            "The FAQ-bypass lane was deliberately disabled — tests pin that even a confident hit "
            "cannot short-circuit the LLM — but the wiring, port, dashboard taxonomy and config "
            "flag were never cut over. build_deps still constructs _FaqBypassAdapter and threads "
            "the embedder into it on every turn; try_answer has zero production call sites; "
            "_resolve_lane only routes clarification/direct_context/agent; BotRun schemas and "
            "the performance dashboard still accept and project a faq_bypass lane/stage; and "
            "Settings keeps faq_fast_lane_enabled with a comment describing the removed "
            "zero-LLM template path. Anyone tracing why faq_bypass never fires must dig through "
            "test names to learn it is intentional."
        ),
        evidence=[
            "backend/app/graph/factories.py:385 — build_deps still constructs `_FaqBypassAdapter(db, clients.embedder, ...)` into GraphDeps on every turn",
            "backend/app/graph/adapters.py:334-362 — _FaqBypassAdapter.try_answer is the only production definition; no call site of try_answer or deps.faq_bypass outside tests",
            "backend/app/graph/runner.py:1015-1055 — _resolve_lane selects only project_clarification → direct_context → agent; 'bypass' does not appear in runner.py",
            "backend/tests/test_graph_runner_turn.py:1394-1396 — test_faq_bypass_hit_cannot_short_circuit_llm pins that the disable is deliberate",
            "backend/app/schemas/bot_run.py:54-55,120-123 and backend/app/reporting/infrastructure/performance_dashboard.py:59-60,508-509 — faq_bypass remains a valid lane/stage value that can no longer occur",
            "backend/app/core/config.py:340-344 — faq_fast_lane_enabled: bool = True with a comment describing the removed template fast lane; grep finds no reader anywhere",
        ],
        impact=(
            "An embedder argument is threaded through build_deps for a lane that cannot fire; "
            "dashboards advertise a phantom lane so operators tuning from stage_timings chase a "
            "structurally unreachable path; a dead Settings flag lets an operator set "
            "FAQ_FAST_LANE_ENABLED=false expecting behavior change and get nothing."
        ),
        fix=(
            "Complete the cutover: delete _FaqBypassAdapter, GraphDeps.faq_bypass + "
            "FaqBypassPort/FaqBypassResult, the factories.py:385 wiring, the faq_bypass entries "
            "in schemas/bot_run.py and performance_dashboard.py, the faq_fast_lane_enabled flag "
            "and its comment, and the removal-pinning tests — after verifying services/retrieval/"
            "faq_bypass.py has no other consumer (the deterministic cascade may be reused "
            "elsewhere). If the seam is being kept for a planned re-enable, instead document the "
            "intentional disable at types.py:133 and stop constructing the adapter per turn. "
            "Bot tool/prompt definitions are approval-gated — get the owner call on "
            "delete-vs-document first."
        ),
        notes="Merged from two lanes (backend perf + docs hygiene), which found the wiring and the flag independently. The related faq_bypass_rule_terms migration 0026 is a different mechanism and stays.",
    ),
    dict(
        id="ARCH-28",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Apply _strip_stale_refusal_rules to the direct-context persona via one shared resolver",
        sev="medium",
        area="architecture",
        labels=["prompts", "drift", "duplication"],
        effort="S",
        problem=(
            "Persona resolution exists in two places with different behavior: the agent lane "
            "fetches the DB persona and strips stale privacy/refusal lines (_strip_stale_"
            "refusal_rules) before use, while the direct-context lane uses the raw "
            "PersonaRepository.active_persona_body with no strip — and the manifest lane "
            "composes policy.persona_body unstripped too. A DB persona still carrying the stale "
            "refusal rules therefore makes the bot refuse/hedge on focused-project turns while "
            "the same persona behaves correctly on agent turns. build_system_prompt even strips "
            "twice (resolve_persona strips, then the caller strips again) — the invariant has no "
            "single owner."
        ),
        evidence=[
            "backend/app/graph/context.py:56-76 — _strip_stale_refusal_rules + resolve_persona strip the DB persona before returning it",
            "backend/app/graph/context.py:135-146 — build_system_prompt's _assemble applies `_strip_stale_refusal_rules(await resolve_persona(…))` — a second strip of already-stripped text — and the error fallback strips AGENT_SYSTEM_PROMPT again",
            "backend/app/graph/adapters.py:286-287 — direct-context lane: `(await PersonaRepository(self._db).active_persona_body(provider)) or AGENT_SYSTEM_PROMPT` with no strip and none of the runtime rules",
            "backend/app/graph/runtime_policy.py:52-63 — build_policy_system_prompt composes `policy.persona_body` unstripped (dormant on prod today: installation_state is empty)",
        ],
        impact=(
            "Inconsistent candidate experience between lanes whenever a persona carries the "
            "legacy refusal lines the strip exists to remove, and any future correction to "
            "persona handling must be replicated per lane — the drift the single-assembly rule "
            "was meant to prevent."
        ),
        fix=(
            "Extract one `resolve_effective_persona(provider)` in context.py (fetch + strip, "
            "used by build_system_prompt) and call it from adapters.py:286; audit whether the "
            "manifest persona build should share it; drop the redundant second strip in "
            "build_system_prompt. This converges the assembly code path only — prompt content "
            "changes stay approval-gated."
        ),
        notes="Carded as structure, not content: no persona text changes required.",
    ),
    # --------------------------------------------------------- FRONTEND --
    dict(
        id="FE-20",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Gate KnowledgeSourceList 5s refresh poller on tab visibility like ExternalSourceList",
        sev="medium",
        area="frontend",
        labels=["frontend", "polling", "regression-risk"],
        effort="S",
        problem=(
            "The wave-1 sweep migrated ExternalSourceList's follow-up polling to TanStack Query "
            "with refetchIntervalInBackground: false, but its sibling KnowledgeSourceList still "
            "runs a raw window.setInterval calling react-admin's useRefresh() every 5 s while "
            "any source is mid-pipeline. The effect has teardown but no visibility gating, so a "
            "hidden tab keeps issuing refetches for as long as a source stays in the pipeline — "
            "and knowledge pipelines are long-running."
        ),
        evidence=[
            "frontend/src/components/atomic-crm/knowledge/KnowledgeSourceList.tsx:131-135 — useEffect creates window.setInterval(() => refresh(), 5000) whenever any source has isPipelineActive; teardown only clears the timer; visibilityState is never consulted (repo-wide grep: only InstallationBootstrap.tsx and ExternalSourceList.test.tsx touch visibility)",
            "frontend/src/components/atomic-crm/knowledge/KnowledgeSourceList.tsx:152-156 — the header renders 'Đang xử lý, tự làm mới mỗi 5 giây', confirming the cadence runs for the whole pipeline duration",
            "frontend/src/components/atomic-crm/projects/ExternalSourceList.tsx:87-94 — the certified sibling derives refetchInterval from row state and sets refetchIntervalInBackground: false ('a hidden tab must not keep hitting the backend')",
            "frontend/src/components/atomic-crm/projects/ExternalSourceList.test.tsx:324-332 — the fixed sibling pins hidden-tab behavior in a test; KnowledgeSourceList has no equivalent",
        ],
        impact=(
            "An operator who leaves a knowledge page open in a background tab keeps the SPA "
            "refetching the knowledge_sources list every 5 s for the full pipeline duration "
            "(tens of minutes), multiplying avoidable backend load and battery drain; the effect "
            "also re-arms on every refetch because sources gets a new array identity each cycle."
        ),
        fix=(
            "Gate the effect on document.visibilityState (skip scheduling when hidden, add a "
            "visibilitychange listener that resumes/clears the interval), or migrate the source "
            "list to TanStack Query with derived refetchInterval + refetchIntervalInBackground: "
            "false mirroring externalSourcePolling.ts. Add a hidden-tab regression test "
            "alongside ExternalSourceList.test.tsx:295-333."
        ),
        notes="Same class as the ExternalSourceList poller fixed in wave 1 — this is the missed sibling, i.e. a sweep regression risk.",
    ),
    dict(
        id="FE-21",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Fix orphaned poll chain in use-project-knowledge-catalog when two revisions are tracked",
        sev="low",
        area="frontend",
        labels=["frontend", "polling", "teardown"],
        effort="S",
        problem=(
            "The category revision poller schedules each hop with pollRef.current = "
            "window.setTimeout(...) and the cleanup clears only that single ref. When "
            "trackRevision is called twice (upload fails review, operator replaces the file), "
            "the second call overwrites pollRef while the first chain is still pending, so the "
            "first chain can no longer be cancelled: unmount or projectId change clears only the "
            "newest timeout and the orphaned chain keeps calling getProjectKnowledgeCategories "
            "and setCategories/notify for up to MAX_POLL_ATTEMPTS×POLL_INTERVAL_MS (~40 s). The "
            "loop also ignores tab visibility entirely."
        ),
        evidence=[
            "frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.ts:56-59 — poll() stores pollRef.current = window.setTimeout(...) on every hop, so the ref only ever names the most recently scheduled timeout",
            "frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.ts:89-95 — the unmount/project-change cleanup clears only pollRef.current, i.e. one chain",
            "frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.ts:97-106 — trackRevision() calls pollUntilActive() without clearing an in-flight chain, so upload followed by replace runs two concurrent poll loops",
            "frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.ts:60-62 — each hop calls loadCatalog() and setCategories() after unmount for an orphaned chain; the branches also notify() (:65-84), so a toast can surface after leaving the page",
        ],
        impact=(
            "After a quick upload-then-replace, every subsequent unmount/project switch leaves a "
            "loop polling getProjectKnowledgeCategories up to 20×2 s and firing a stray success/"
            "failure toast afterward; hidden tabs additionally poll when nothing is watching."
        ),
        fix=(
            "Store a generation/epoch counter (or clear pollRef at the top of pollUntilActive "
            "and check it inside each hop before rescheduling) so a new trackRevision cancels "
            "the previous loop; also skip scheduling when document.visibilityState is hidden and "
            "resume on visibilitychange, matching the ExternalSourceList convention."
        ),
        notes="Bounded (MAX_POLL_ATTEMPTS = 20 at :26), hence low; same visibility-gating family as FE-20 — fix together.",
    ),
    dict(
        id="FE-22",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Certify or flatten integrations/ layer skeleton that the DDD matrix leaves unenforced",
        sev="medium",
        area="frontend",
        labels=["architecture", "frontend", "enforcement-gap"],
        effort="M",
        problem=(
            "The sweep rebuilt integrations/ with the DDD directory skeleton (domain/, "
            "application/, presentation/ plus a root api.ts gateway), but the certified "
            "dependency matrix in backend/tests/test_architecture_boundaries.py only enforces "
            "knowledge, leads, personas, projects, and reporting. The layer rules never fire for "
            "integrations, and its layers already sit in directions the certified rules forbid "
            "elsewhere: the application layer imports the api.ts gateway (which imports "
            "@/lib/apiClient), domain imports types from that transport module, and presentation "
            "reaches past application into ../api and the root-level SettingsFieldStatus."
        ),
        evidence=[
            "backend/tests/test_architecture_boundaries.py:243-246 — _FRONTEND_LAYERED_FEATURE_ROOTS covers only knowledge, leads, personas, projects, reporting; 'integrations' is absent",
            "frontend/src/components/atomic-crm/integrations/application/useSettingsBundle.ts:9-14 — the application layer imports zaloIntegrationGateway from ../api, whose first import is apiJson from @/lib/apiClient (integrations/api.ts:1-2) — the exact application→lib edge certified features forbid",
            "frontend/src/components/atomic-crm/integrations/application/useZaloForm.ts:5 — same edge: application hook imports the gateway from ../api",
            "frontend/src/components/atomic-crm/integrations/domain/providerDescriptors.ts:12-13 — domain imports type SecretStatus from ../api, tying domain to the transport module",
            "frontend/src/components/atomic-crm/integrations/presentation/ZaloChannelSection.tsx:6-8 — presentation imports ../api types and the root-level ../SettingsFieldStatus, bypassing the application layer",
        ],
        impact=(
            "Nothing stops integrations/ from drifting further, and the file layout misleads "
            "contributors into thinking the layers are enforced like projects/ or leads/. The "
            "next person adding the feature to the matrix inherits 4+ pre-existing violations to "
            "untangle."
        ),
        fix=(
            "Either (a) finish the migration: define an integrations/application port (like "
            "project-knowledge-port.ts), move the gateway behind integrations/infrastructure/, "
            "point application hooks at the port, and add 'integrations' to "
            "_FRONTEND_LAYERED_FEATURE_ROOTS with composition-module entries; or (b) explicitly "
            "flatten the domain/application/presentation dirs with a comment that the feature is "
            "uncertified, so nobody mistakes them for enforced layers."
        ),
        notes="Distinct from the two known QA-blocked edges (FE-02/FE-08 application-layer edges, ChatThread/use-conversation-actions provider seam) — this is a whole unenforced feature tree.",
    ),
    dict(
        id="FE-23",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Prune ~45 unreferenced keys from vietnameseCrmMessages.ts",
        sev="low",
        area="frontend",
        labels=["frontend", "i18n", "dead-code"],
        effort="S",
        problem=(
            "The post-sweep catalog carries a large set of keys no translate()/notify() call can "
            "ever reach. Whole blocks are orphaned: leftovers from pre-sweep pages "
            "(settings/theme/login screens rebuilt with hardcoded Vietnamese) and from duplicate "
            "resources.conversations takeover/release clusters that predate the top-level keys "
            "now in use."
        ),
        evidence=[
            "frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:173-187 — crm.settings block: zero translate() references anywhere in frontend/src",
            "frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:188-193 — crm.theme block unreferenced; :221-242 crm.auth block unreferenced (login pages hardcode Vietnamese instead)",
            "frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:165-171 — crm.navigation: only .overview is used (RecruitingCommandCenter.tsx:203); label/messages/projects/settings/performance/account are dead",
            "frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:36-43 — resources.conversations.takeover/release are unreachable duplicates of conversations.takeover/release (:154-161) and have diverged ('Tiếp nhận thất bại' vs 'Tiếp nhận hội thoại thất bại')",
            "frontend/src/components/atomic-crm/providers/commons/vietnameseCrmMessages.ts:196-208,:248-251 — crm.profile.record_not_found, crm.common copy/copied/loading/load_failed, 'ra-auth'.auth.forgot_password have no local references",
        ],
        impact=(
            "~45 phantom keys imply coverage that does not exist: anyone localizing or auditing "
            "UI text must diff every key by hand, and the divergent takeover/release duplicates "
            "risk someone 'fixing' the live copy in the dead one. The catalog grows "
            "monotonically because nothing flags unreferenced keys."
        ),
        fix=(
            "Delete the dead subtrees (crm.settings, crm.theme, crm.auth, the six unused "
            "crm.navigation keys, crm.profile.record_not_found, crm.common copy/copied/loading/"
            "load_failed, resources.conversations.takeover/release, ra-auth pending a ra-core "
            "ForgotPasswordPage check). If the strings are wanted for upcoming pages, re-add "
            "them together with the consuming translate() call."
        ),
        notes="Sweep-derived, not style: the catalog is the single translation source for ra-core/product strings, so unreferenced keys are dead code by definition here.",
    ),
    dict(
        id="FE-24",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Route semi_auto takeover and integration-button strings through the message catalog",
        sev="low",
        area="frontend",
        labels=["frontend", "i18n", "consistency"],
        effort="S",
        problem=(
            "Components rebuilt in the sweep inconsistently straddle the two idioms: the same "
            "JSX expression calls translate('crm.common.*') on one branch and embeds an "
            "identical-purpose Vietnamese literal on the other; the conversation takeover flow "
            "added a semi_auto mode whose success/error strings bypass the catalog while its "
            "sibling modes use catalog keys; ProfilePage passes messageArgs._ overrides that "
            "shadow catalog entries it already defines."
        ),
        evidence=[
            "frontend/src/components/atomic-crm/conversations/presentation/use-conversation-actions.ts:66-80 — human/bot branches notify catalog keys (:67,:70) but the semi_auto branches notify literals 'Đã bật chế độ bán tự động'/'Không thể bật chế độ bán tự động' (:69,:78)",
            "frontend/src/components/atomic-crm/integrations/presentation/ZaloChannelSection.tsx:115-117 — ternary mixes translate('crm.common.testing') with literal 'Lưu & kiểm tra'; repeated at :188-190",
            "frontend/src/components/atomic-crm/integrations/presentation/JevSection.tsx:131-138 — footer mixes translate('crm.common.saving'/'crm.common.save_changes') with literal 'Token được mã hoá, không hiển thị lại.'; same in LlmProvidersSection.tsx:275-283",
            "frontend/src/components/atomic-crm/knowledge-base/KnowledgeBaseShow.tsx:396-399 — 'Lưu tệp' literal as the non-pending label while the pending label is translate('crm.common.saving'); same split in FacebookMessengerIntegrationPage.tsx:412-414 and FacebookMessengerPageCard.tsx:110-112",
            "frontend/src/components/atomic-crm/settings/ProfilePage.tsx:69-82 — notify('crm.profile.updated', { messageArgs: { _: 'Thông tin đã được cập nhật' } }) overrides the catalog copy with an inline string; likewise update_error at :79-82",
        ],
        impact=(
            "Copy for the same action lives in two places, so edits diverge (already happened "
            "with takeover.error), and the semi_auto notifications can never be reworded or "
            "localized without touching component code; reviewers can no longer treat 'uses the "
            "catalog' as an invariant on new UI."
        ),
        fix=(
            "Add conversations.takeover.semantic_auto_{success,error} (or equivalent) to the "
            "catalog and use them in use-conversation-actions.ts:69,78; add the integration "
            "button/footer strings to the catalog and replace the literals in ZaloChannelSection, "
            "JevSection, LlmProvidersSection, FacebookMessengerIntegrationPage, "
            "FacebookMessengerPageCard, KnowledgeBaseShow; drop the messageArgs._ overrides in "
            "ProfilePage so the catalog values win. Fix alongside FE-23 — same catalog file."
        ),
        notes="Scoped to mixed-idiom sites; whole pages that hardcode Vietnamese by convention are the established pattern and not carded.",
    ),
    dict(
        id="FE-25",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Sync registry.json dependencies block with package.json before next registry:build",
        sev="low",
        area="frontend",
        labels=["ops", "registry", "dead-config"],
        effort="S",
        problem=(
            "The registry generator preserves whatever dependencies array is checked in (it only "
            "rewrites files and spreads the rest of the item), so the manifest still lists the "
            "upstream atomic-crm dependency set even though package.json dropped them and no src "
            "file imports them. Anyone installing the published block gets 11 dead packages; the "
            "drift is invisible to the registry:check gate, which validates paths and local "
            "imports only."
        ),
        evidence=[
            "frontend/registry.json:19-33 — items[0].dependencies advertises @hello-pangea/dnd, @nivo/bar, faker, papaparse, jsonexport, @streamparser/json-whatwg, mime, ra-supabase-core, ra-supabase-language-english, @tanstack/query-async-storage-persister, @tanstack/react-query-persist-client",
            "frontend/package.json:36-80 — none of those packages appear in dependencies; repo-wide grep for nivo|faker|jsonexport|streamparser|papaparse|hello-pangea in frontend/src returns zero imports",
            "frontend/scripts/generate-registry.mjs:78-90 — the generator rewrites only the files array and spreads ...item otherwise, so the stale dependencies list can never self-heal",
            "frontend/scripts/check-registry-paths.mjs:20-42 — the CI-enforced checker validates manifest paths, duplicates, and test-file leaks but never inspects the dependencies array",
        ],
        impact=(
            "Running npm run registry:build publishes a block whose install list pulls heavy "
            "unused packages (nivo, faker, dnd) into consumer apps and references ra-supabase "
            "adapters this fork replaced."
        ),
        fix=(
            "In generate-registry.mjs, derive dependencies from package.json (intersected with "
            "what registry files import, or simply replace the hardcoded list) and regenerate "
            "registry.json; at minimum hand-edit registry.json:19-33 down to the packages the "
            "registry files actually import (zod, marked, dompurify)."
        ),
        notes="File-path half is already safe: quality-gates.yml:154-155 runs npm run registry:check — only the dependencies block drifts.",
    ),
    dict(
        id="FE-26",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Four orphaned frontend devDependencies: @inquirer/prompts, @types/papaparse, @types/qs, @types/ms",
        sev="low",
        area="frontend",
        labels=["frontend", "dependencies", "hygiene"],
        effort="S",
        problem=(
            "Four devDependencies have zero usage anywhere in the frontend: @inquirer/prompts is "
            "imported by no script, config, or test; @types/papaparse, @types/qs and @types/ms "
            "type packages that are not dependencies and are never imported. They look like "
            "leftovers from the wave-1 six-package orphan removal that dropped the packages but "
            "not their type/CLI companions."
        ),
        evidence=[
            "frontend/package.json:79 — \"@inquirer/prompts\": \"^8.2.0\" (devDependencies); no @inquirer import in src/, e2e/, scripts/, or configs",
            "frontend/package.json:85-86 — \"@types/papaparse\", \"@types/qs\"; no `from \"papaparse\"` / `from \"qs\"` import exists (papaparse appears only as a third-party entry in registry.json:24, a manifest, not an import or installed dep)",
            "frontend/package.json:83 — \"@types/ms\"; no `from \"ms\"` import exists anywhere",
            "frontend/scripts/generate-registry.mjs:3 — `import { globSync } from \"glob\"` confirms the remaining dev tooling (glob, globals, typescript-eslint, eslint-plugin-react-refresh, @vitest/browser-playwright) is genuinely used and was checked",
        ],
        impact=(
            "Install weight and lockfile churn for types of packages that are not even "
            "installed; mild signal noise for the next orphan sweep."
        ),
        fix=(
            "Remove the four entries from frontend/package.json devDependencies and run npm "
            "install to sync package-lock.json. Dependency manifests are approval-gated per "
            "AGENTS.md — get the owner sign-off with the removal diff."
        ),
        notes="daisyui, tw-animate-css, @tailwindcss/typography and @fontsource/be-vietnam-pro were checked and ARE used via src/index.css — not orphans.",
    ),
    # ---------------------------------------------------------- TESTING --
    dict(
        id="TEST-16",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Execute bg_deploy's rolling turn-worker recreate in the sandbox instead of pinning it as script text",
        sev="medium",
        area="testing",
        labels=["regression-test", "deploy", "bg-deploy"],
        effort="M",
        problem=(
            "The 2026-09-26 bot-silence incident produced two deploy-path fixes: worker-chatbot "
            "is now rolled one replica at a time (rolling_recreate_service) and a "
            "turn_pipeline_check gate must pass before flip. test_deployment_makefile.py pins "
            "both only as raw script text, and its executed sandbox can never reach the rolling "
            "branch: the stubbed docker emits no `compose config` JSON, so declared_replicas "
            "falls back to 1 and rolling_recreate_service takes its documented '1 replica, "
            "single recreate' early return. The one-at-a-time replacement loop, the 180s "
            "healthy-budget wait, and the failure branches of both gates have never been "
            "executed by any test."
        ),
        evidence=[
            "backend/scripts/bg_deploy.sh:145-188 — rolling_recreate_service replaces stale replicas one at a time, waiting for a healthy replacement between replacements (the 09-26 outage fix)",
            "backend/scripts/bg_deploy.sh:69-71 — declared_replicas echoes 1 when `docker compose config` output is empty/invalid",
            "backend/tests/test_deployment_makefile.py:434-474 — the sandbox docker stub handles compose pull/up/ps/inspect/rm but has no `compose config` branch; unknown commands exit 0 with empty stdout, so declared_replicas always falls back to 1",
            "backend/tests/test_deployment_makefile.py:684-692 — the test comment admits the stub 'cannot report replicas' and only asserts the single-recreate command",
            "backend/tests/test_deployment_makefile.py:820-850 — the only rolling-path pins are source-text assertions (TURN_WORKERS literal, --no-recreate/--scale substrings, gate ordering)",
            "backend/scripts/bg_deploy.sh:291-297 — post-flip turn_pipeline_check gate; the sandbox stub answers `compose exec -T web-* python -m` with silent exit 0, so its failure/rollback branch is unexecuted",
        ],
        impact=(
            "The exact regression class that caused the 2026-09-26 bot-silence outage (a bug in "
            "stale_service_container selection, the wait/budget loop, the --scale bookkeeping, "
            "or the consumer-gate ordering) can ship while every text pin still passes. The "
            "deploy pipeline gate's failure path is equally unexecuted — a stalled pipeline "
            "would no longer abort the deploy and nobody would notice until prod."
        ),
        fix=(
            "Extend the sandbox docker stub to answer `docker compose config --format json` with "
            "a fixture declaring worker-chatbot deploy.replicas=3 (and compose ps -q with 3 "
            "cids). Then assert: (1) the deploy command sequence removes and recreates one "
            "replica at a time with --scale bookkeeping, never a single force-recreate of all "
            "three; (2) a rolled replica that never reports healthy triggers the 180s-budget "
            "warning plus the consumer-gate abort before flip_caddy.sh; (3) a non-zero "
            "turn_pipeline_check aborts into bg_rollback.sh. Keep or drop the 820-850 text pins "
            "once the behavior is executed."
        ),
        notes="The incident fix itself is good and (pending OPS-25) written — this card is only the untested execution path.",
    ),
    dict(
        id="TEST-17",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Retire the TEST-10 raw-source assertion tail: it grew from ~30 pins in 7 files to ~135 in 14",
        sev="medium",
        area="testing",
        labels=["raw-source-assertions", "frontend", "test-debt"],
        effort="L",
        problem=(
            "TEST-10's deferred tail was ~30 raw-source assertions in 7 files. Recounting at "
            "HEAD: 9 frontend test files import ~30 production files via `?raw` and make ~120 "
            "expect-sites against that text (CSS selector/property regexes plus literal TSX "
            "source strings), and 5 backend test files make ~13 more string-level assertions "
            "against app/migration/script/test sources — ≈135 sites across 14 files, >4x the "
            "baseline. Wave 1 already proved the better pattern twice (mobile-workspace and the "
            "inbox layout tests render real components and assert computed styles), but the bulk "
            "of the class was added/kept while colocating feature tests."
        ),
        evidence=[
            "frontend/src/components/atomic-crm/integrations/settings.css.test.ts:3-14,83-104 — imports 4 TSX sources + 2 stylesheets ?raw; ~24 toMatch/toContain sites incl. literal JSX strings in ZaloIntegrationPage.tsx",
            "frontend/src/components/atomic-crm/users/account-layout-regressions.test.ts:42-52 — asserts zod schema calls inside UserCreate.tsx/UserEdit.tsx source",
            "frontend/src/components/atomic-crm/personas/persona-layout-regressions.test.ts:13-16,53 — counts source occurrences and forbids literal strings in PersonaList.tsx",
            "frontend/src/components/atomic-crm/projects/projects.css.test.ts:7-79, knowledge/knowledge-workspace-layout.test.ts:10-53, performance/performance.css.test.ts:6-59, kit/tailkit-system.css.test.ts:7-27, conversations/inbox/responsive-visual-regressions.test.ts:8-33 — five more files, ~80 further regex-against-CSS-source assertions",
            "frontend/src/components/atomic-crm/layout/mobile-workspace.test.tsx:41-101 — the converted exemplar: same concerns pinned via rendered getComputedStyle output",
            "backend/tests/test_external_source_sync_worker.py:93-97, test_external_source_sync.py:665-669, test_runtime_authority_stamps.py:54-59, test_security_headers.py:49-90, test_universal_platform_characterization.py:281-283 — backend tail (~13 sites) incl. a test asserting marker strings inside other test files' source",
        ],
        impact=(
            "Every styling pass or legit refactor of these components/stylesheets must edit "
            "byte-exact regexes in up to 14 test files; the raw pins also defeat minification/"
            "selector reordering and teach the suite to pass while real rendering breaks (text "
            "present ≠ rule applied). The backend meta-test couples CI to test-file wording, "
            "producing false failures during test refactors."
        ),
        fix=(
            "Two stages. (1) Freeze the class: convert the TSX-source assertions (settings.css, "
            "account-layout-regressions, persona-layout-regressions, knowledge-workspace-layout, "
            "backend test_universal_platform_characterization:281-283) to rendered-output or "
            "behavior assertions. (2) Batch the CSS-text pins (projects, performance, tailkit, "
            "responsive-visual-regressions, remaining settings/knowledge rules) into "
            "per-workspace rendered-layout specs following mobile-workspace.test.tsx, or fold "
            "genuinely global rules into the existing css-scoping ratchet. Delete the backend "
            "string pins in favor of the executed calls they describe."
        ),
        notes="Closes the sweep-ledger TEST-10 tail item at its new, larger size — the ledger's ~30/7 figure is stale.",
    ),
    dict(
        id="TEST-18",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Engage the backend coverage ratchet: fail_under is still 0 so the CI 'coverage gate' cannot fail",
        sev="low",
        area="testing",
        labels=["coverage", "ci", "ratchet"],
        effort="S",
        problem=(
            "The backend coverage gate is labeled as a gate but cannot fail: .coveragerc sets "
            "fail_under = 0 with a comment promising the first CI run's measured number becomes "
            "a never-lowered ratchet floor. CI has run repeatedly since (wave 1 close plus the "
            "09-26 deploys), yet the floor is still 0 — backend coverage can regress to any "
            "number without a red build."
        ),
        evidence=[
            "backend/.coveragerc:14-17 — 'Report-only for now: no fail_under yet. The first CI run's measured number becomes the ratchet floor; raise it only, never lower.' followed by fail_under = 0",
            ".github/workflows/quality-gates.yml:61-62 — step 'Backend unit tests (coverage gate)' runs pytest --cov, which cannot fail on coverage while fail_under=0",
            "frontend/vitest.config.ts:19-53 — the frontend counterpart is a real ratchet: thresholds 67/55/57/68 whole-tree plus per-file 80% floors",
        ],
        impact=(
            "A PR deleting tests or gating new graph/services code behind untested paths keeps "
            "the 'coverage gate' step green. The two-day-old promise in the comment is already "
            "stale, so the ratchet, if never raised, becomes permanent dead config."
        ),
        fix=(
            "Run the backend unit lane once with --cov, read the measured total, set "
            "backend/.coveragerc fail_under to that number minus ~1pt (the same absorption "
            "margin the frontend floors use), and delete the 'Report-only for now' comment. "
            "Optionally echo the total in the CI step log so the next raise is a one-line diff."
        ),
        notes="CI files are deployment-adjacent — the one-line .coveragerc change is the safe half; the workflow needs no edit.",
    ),
    dict(
        id="TEST-19",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Install the functional-e2e backend from uv.lock instead of unpinned pip -e .[dev]",
        sev="low",
        area="testing",
        labels=["ci", "dependencies", "reproducibility"],
        effort="S",
        problem=(
            "functional-e2e is the only backend job that ignores the lockfile: it creates a venv, "
            "upgrades pip unpinned, and installs -e .[dev] with fresh resolution, while "
            "backend-unit, backend-integration, release-gate, and dependency-audit all install "
            "via `uv sync --all-extras --frozen`. The two highest-blast-radius journeys therefore "
            "execute against dependency versions nothing else in CI (and not the shipped image) "
            "has verified."
        ),
        evidence=[
            ".github/workflows/quality-gates.yml:49-50,115-116,336-337,411-412 — backend-unit, backend-integration, release-gate, dependency-audit all run `uv sync --all-extras --frozen`",
            ".github/workflows/quality-gates.yml:219-222 — functional-e2e instead runs `pip install --upgrade pip` (unpinned) and `pip install -e .[dev]`, resolving fresh from pyproject ranges",
            "backend/pyproject.toml:9-10 — 'Exact versions come from uv.lock: the image and CI install from it' — which the e2e job's install method contradicts",
        ],
        impact=(
            "A transitive bump that only resolves under pip's looser resolution can break the "
            "e2e journeys (or silently change behavior under test) while the locked lanes stay "
            "green — the two lanes can disagree about which code passed. Fresh resolution also "
            "makes e2e the least reproducible job on every run."
        ),
        fix=(
            "Replace the venv+pip steps with the same astral-sh/setup-uv@v5 + `uv sync "
            "--all-extras --frozen` pair the other jobs use (the pip cache line can go). If the "
            "e2e job intentionally wants a lighter install, use `uv sync --frozen --no-dev` plus "
            "the playwright extra rather than a fresh pip resolve. CI files are approval-gated."
        ),
        notes="Dependabot pip-vs-uv.lock is a known watch item and unchanged — this card is the CI job, not the dependabot config.",
    ),
    dict(
        id="TEST-20",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Hoist the triplicated _reset_local_secret_cache autouse fixture into tests/conftest.py",
        sev="low",
        area="testing",
        labels=["fixtures", "flake-risk", "isolation"],
        effort="S",
        problem=(
            "The process-local secret cache in app.core.preamble_cache leaks decrypted values "
            "across tests in one process. Three files each define an identical autouse fixture "
            "calling preamble_cache._reset_local_secret_cache() around every test; the "
            "protection exists only where someone remembered to paste it. Any fourth test file "
            "that resolves a secret through the cache without its own copy reintroduces the "
            "cross-file pollution class the HEAD commit just fixed for the facebook reveal "
            "tests."
        ),
        evidence=[
            "backend/tests/test_facebook_oauth.py:30-42 — autouse _reset_local_secret_cache with docstring explaining a cached value from another test file shadows this module's env-backed stubs",
            "backend/tests/test_integration_settings.py:76-80 — same fixture, body only, no comment",
            "backend/tests/test_preamble_cache.py:21-25 — same fixture, third copy",
            "backend/tests/conftest.py:36-51 — existing autouse pattern (_isolate_redis) showing where a shared reset belongs",
        ],
        impact=(
            "The next test that reads or reveals a cached secret will copy the same boilerplate "
            "or, more likely, forget it and land an order-dependent suite that passes in "
            "isolation and fails in the full run."
        ),
        fix=(
            "Move one implementation into backend/tests/conftest.py as an autouse fixture (it is "
            "cheap: two cache clears) or expose it as a named fixture the three files request; "
            "delete the three local copies. Keep it autouse so future secret-touching tests are "
            "covered without remembering the incantation."
        ),
        notes="Root-caused by 31d30377 (HEAD, 'isolate the facebook reveal tests…') — the fix stayed file-local instead of moving to conftest.",
    ),
    dict(
        id="TEST-21",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Exercise progressive_send in scripts/smoke_turn.py so the pre-flip gate covers the streaming path",
        sev="medium",
        area="testing",
        labels=["testing", "release-gate", "progressive-send"],
        effort="M",
        problem=(
            "The blue-green pre-flip smoke gate builds GraphDeps without `progressive_send`, "
            "which defaults to False, so the gate exercises only the legacy single-message "
            "delivery path. Production serves the progressive two-bubble path (deployed and "
            "prod-proven in 684bd3ef), meaning the release gate validates a materially different "
            "delivery pipeline than the one candidates receive — a regression in "
            "_await_first_bubble/_complete_progressive_prefix (including REL-13's failure-path "
            "corruption) sails through the flip. The stub agent also never invokes on_delta, so "
            "simply flipping the flag would silently no-op."
        ),
        evidence=[
            "backend/scripts/smoke_turn.py:103-117 — _build_smoke_deps constructs GraphDeps without `progressive_send`",
            "backend/app/graph/types.py:150-155 — `progressive_send: bool = False` default on GraphDeps",
            "backend/app/graph/runner.py:186-199 — _progressive_send_enabled requires the flag plus the durable dispatcher seam before any bubble path opens",
            "backend/scripts/smoke_turn.py:8-19 — the docstring claims the gate exercises 'the exact regression surface' behind the production outages",
            "backend/tests/test_graph_runner_turn.py:2999-3077 — runner-level progressive tests cover only happy paths; no runner test drives LLMThrottled or an agent error after the early bubble",
        ],
        impact=(
            "The newest, riskiest delivery machinery ships to prod gated only by unit tests with "
            "fakes; the one end-to-end pre-flip check that runs against the real "
            "ConversationService cannot see it."
        ),
        fix=(
            "Add a streaming variant to smoke_turn.py: a stub agent that feeds text through "
            "on_delta, `progressive_send=True`, plus assertions that the early bubble and "
            "remainder persist with correct terminal message/outbox states (mirroring "
            "_assert_persisted_delivery_invariant); optionally add the runner-level "
            "failure-after-bubble tests from REL-13."
        ),
        notes="Pairs with REL-13 — the gate extension is what would have caught it.",
    ),
    # ------------------------------------------------------------- DOCS --
    dict(
        id="DOC-14",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Fix TECH.md's five stale claims: Alembic head 0054, two-project Vitest, RetrievalPort, dead GraphDeps.safety seam",
        sev="medium",
        area="docs",
        labels=["documentation", "tech-debt", "agent-context"],
        effort="S",
        problem=(
            "The post-sweep commits (migration 0055, the safety-layer removal/think-strip "
            "rename, the GraphRetrievalPort seam typing, the vitest claude-project removal) "
            "landed after TECH.md was last aligned, and five of its normative claims no longer "
            "match the tree. Because CI's docs-drift guard only checks deployment-guide.md's "
            "Alembic head, TECH.md rots silently."
        ),
        evidence=[
            "TECH.md:21 — 'hand-written (0001–0054, current head `0054_channel_account_projects`)'; backend/alembic/versions/0055_memories_match_halfvec.py:36-37 declares revision 0055 revising 0054",
            "TECH.md:52 — 'Tests — Vitest 4 (two projects: `app` Playwright browser, `claude` Node)'; frontend/vitest.config.ts:9 says 'One test project' and package.json:5-11 defines no test:unit:claude",
            "TECH.md:87-88 — graph layer 'depends on Protocol interfaces (ConversationPort, RetrievalPort, LeadContextPort, FaqBypassPort)'; ports.py defines no RetrievalPort — the protocol is GraphRetrievalPort (ports.py:218, exported :265), plus TurnDecisionsPort (:62), RuntimePolicyPort (:208), DirectContextPort (:250)",
            "TECH.md:105-106 — '`GraphDeps.safety` is an unwired seam… (`MiniMaxSafety` has no call site)'; repo-wide grep finds zero hits and GraphDeps (graph/types.py:122-134) has no safety field — removed by 38ad9d6a",
            ".github/workflows/quality-gates.yml (backend-unit 'Docs drift check') — the CI guard greps only ../docs/deployment-guide.md for the current alembic head; TECH.md's head claim has no guard",
        ],
        impact=(
            "TECH.md is AGENTS.md's declared 'system map and stack' source of truth that agents "
            "load first. An agent writing migration 0056 from TECH.md:21 sets down_revision=0054 "
            "and creates an Alembic multiple-heads break. The phantom safety seam and wrong port "
            "names send readers hunting for symbols that no longer exist, and the vitest claim "
            "breaks `npm run test:unit:claude` for anyone who runs the documented command."
        ),
        fix=(
            "Five one-line edits in TECH.md: :21 → head 0055_memories_match_halfvec; :52 → one "
            "Vitest project; :87-88 → the real seam set (ConversationPort, GraphRetrievalPort, "
            "LeadContextPort, FaqBypassPort, TurnDecisionsPort, RuntimePolicyPort); :105-107 → "
            "replace the safety-seam paragraph with the current statement that the only "
            "user-visible reply transform is graph/think_strip.py:strip_think_reasoning. Then "
            "harden CI: extend the docs-drift step to grep TECH.md's head marker too, or drop "
            "the revision id from TECH.md and link deployment-guide.md:242 as the single "
            "guarded source."
        ),
        notes="Port-name drift also live in docs/testing.md:44 and standards/coding-style.md:22 (DOC-15/DOC-17); migration head is correct in docs/deployment-guide.md:242 (CI-guarded).",
    ),
    dict(
        id="DOC-15",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Rewrite docs/testing.md sections that document removed or inverted test infrastructure",
        sev="medium",
        area="docs",
        labels=["documentation", "testing", "ci"],
        effort="M",
        problem=(
            "docs/testing.md still describes the pre-sweep test infrastructure in five places: "
            "the deleted claude vitest project and its npm script, the old three-file-only "
            "coverage policy (now inverted into a whole-tree ratchet), a CI jobs table that "
            "predates the functional-e2e split, a removed test_fast_lane.py, and the old port "
            "names."
        ),
        evidence=[
            "docs/testing.md:100-101,:117 — documents a `claude` Vitest project and `npm run test:unit:claude`; vitest.config.ts defines exactly one project and package.json has no such script (removed in 'drop the dead vitest claude project script')",
            "docs/testing.md:100,:184 — 'The enforced 80% coverage threshold applies only to the changed/high-risk surface'; vitest.config.ts:19-53 now enforces whole-tree ratchet floors 67/55/57/68 over all of atomic-crm plus three 80% per-file gates — the doc denies a threshold that now exists",
            "docs/testing.md:170-174 — CI table lists backend-unit without the docs-drift/coverage steps, omits functional-e2e entirely, and describes visual-e2e as chromium+Mobile Chrome; quality-gates.yml actually defines six jobs with functional-e2e (matrix chromium/Mobile Chrome) and visual-e2e (visual projects only, zero-backend)",
            "docs/testing.md:52,:69 — cites test_fast_lane.py and `pytest -k \"test_fast_lane\"`; no such file exists and test_model_tiering.py:16-17 records 'The template fast lane was removed'",
            "docs/testing.md:44 — port list includes the nonexistent RetrievalPort (actual exports: graph/ports.py:261-266)",
        ],
        impact=(
            "testing.md is AGENTS.md's designated testing source of truth. `npm run "
            "test:unit:claude` fails with 'missing script'; an agent that trusts :184 may delete "
            "non-three-file tests believing nothing else gates coverage, then fail the CI "
            "ratchet; the CI table misroutes debugging (a chromium/Mobile Chrome failure lands "
            "in visual-e2e per the doc, but that job doesn't run those projects); the fast-lane "
            "row sends contributors to a file that no longer exists."
        ),
        fix=(
            "One docs/testing.md pass: delete the claude-project bullet and the test:unit:claude "
            "command (:100-101,:117); rewrite :100/:184 to the whole-atomic-crm ratchet "
            "(67/55/57/68 floors + three 80% gates); rebuild the CI table from quality-gates.yml's "
            "six jobs including functional-e2e; replace the Fast-lane row :52 with the current "
            "graph lane files (test_graph_decisions.py, test_model_tiering.py) and drop the -k "
            "example :69; correct :44 to GraphRetrievalPort. Note backend coverage is "
            "report-only (TEST-18) if the coverage section is rewritten."
        ),
        notes="Pure doc drift; cross-ref TEST-18 (the ratchet itself) is a separate fix.",
    ),
    dict(
        id="DOC-16",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Replace react-virtuoso mandates and the 65-test-file count across standards/ and docs/ checklists",
        sev="medium",
        area="docs",
        labels=["documentation", "tech-debt", "standards"],
        effort="S",
        problem=(
            "The virtua-for-react-virtuoso migration (TECH.md:49 records react-virtuoso as "
            "removed) never reached seven checklist/standards/QA locations that still mandate "
            "the removed library, and the DoD still cites a test-file count from months ago. "
            "These are the normative completion/review gates agents are told to apply."
        ),
        evidence=[
            "standards/performance.md:136 — '**react-virtuoso** required for long lists: conversations, messages, bot runs'; frontend/package.json:73 lists virtua ^0.49.2 and no react-virtuoso exists in any manifest (TECH.md:49 states it was removed)",
            "standards/definition-of-done.md:72, standards/review-checklist.md:27, standards/ui-guidelines.md:75, standards/prompt-library/README.md:180 — all four mandate react-virtuoso for long lists",
            "standards/definition-of-done.md:40 — 'Backend: .venv/bin/pytest ... all 65 test files pass'; backend/tests holds 188 unit test files (plus ~15 integration)",
            "docs/qa-runbook.md:406-407 — '`conversations` and `bot_runs` use `react-virtuoso` (per docs/HLD.md)'; the runtime uses virtua VList (ChatThread.tsx)",
            "docs/code-standards.md:188-190 — correctly says 'Use virtua (VList)' but its parenthetical 'react-virtuoso is also in deps' is now false",
        ],
        impact=(
            "An implementer obeying standards/performance.md or ui-guidelines.md installs "
            "react-virtuoso — tripping AGENTS.md's dependency-change approval gate and "
            "reintroducing a deliberately removed dependency; the QA runbook verifies the wrong "
            "DOM; the '65 test files' figure makes the DoD test gate look satisfied at ~1/3 of "
            "the suite."
        ),
        fix=(
            "Sweep react-virtuoso → virtua across standards/performance.md:136, definition-of-"
            "done.md:72, review-checklist.md:27, ui-guidelines.md:75, prompt-library/README.md:180, "
            "qa-runbook.md:406-407, and drop the stale parenthetical at code-standards.md:189. "
            "Update definition-of-done.md:40 to 'all unit + integration tests pass' (drop the "
            "hardcoded count). Use TECH.md:49 as the wording source."
        ),
        notes="Wave-1 docs work did not cover standards/; this is the residual.",
    ),
    dict(
        id="DOC-17",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Correct the phantom RetrievalPort protocol name in standards/coding-style.md and docs/testing.md",
        sev="low",
        area="docs",
        labels=["documentation", "tech-debt"],
        effort="S",
        problem=(
            "The retrieval Protocol was renamed/typed as GraphRetrievalPort during the seam "
            "work, but two convention/test docs still cite a RetrievalPort symbol that does not "
            "exist, so the canonical DI example in the coding standard is unimplementable as "
            "written."
        ),
        evidence=[
            "standards/coding-style.md:22 — 'The graph layer depends on `Protocol` interfaces (`ports.py`: `ConversationPort`, `RetrievalPort`, `LeadContextPort`, `FaqBypassPort`)'; no RetrievalPort symbol exists anywhere in backend/",
            "backend/app/graph/ports.py:218 — GraphRetrievalPort (composed of ProjectKnowledgeQueryPort, PersonaBodyResolver, RecommendationQueryPort, …), exported at ports.py:261-266 alongside LeadContextPort and LeadGenderPort",
            "docs/testing.md:44 — same four-name list presented as the pattern tests must fake",
            "docs/HLD.md and docs/system-architecture.md contain no RetrievalPort hits — only TECH.md:87 (DOC-14), testing.md:44 (DOC-15) and coding-style.md:22 carry the stale name",
        ],
        impact=(
            "A contributor writing a fake for the retrieval dependency per the doc implements a "
            "protocol that doesn't exist, and typed fakes fail mypy against the real "
            "GraphDeps.retrieval: GraphRetrievalPort annotation (graph/types.py:123)."
        ),
        fix=(
            "In standards/coding-style.md:22 replace RetrievalPort with GraphRetrievalPort (and "
            "optionally add LeadGenderPort/TurnDecisionsPort so the list matches ports.py's "
            "__all__). Keep this edit in the same commit as the DOC-14/DOC-15 port fixes so the "
            "port list is identical everywhere."
        ),
        notes="Deliberately scoped to the two sites not covered by DOC-14/DOC-15 so the port-name fix is one grep-verified pass.",
    ),
    dict(
        id="DOC-18",
        date=AUDIT_DATE,
        audit_head=AUDIT_HEAD,
        title="Fix codebase-summary.md's stale tree rows: migration ceiling, phantom graph/tools.py, 13-service enumeration",
        sev="low",
        area="docs",
        labels=["documentation", "tech-debt"],
        effort="S",
        problem=(
            "Three rows in the repository map predate the post-sweep changes: the migration "
            "ceiling, a key-file that no longer exists (split into the graph/tools/ package with "
            "TOOL_SCHEMAS moved to schemas.py), and a prod-service enumeration that never "
            "included the metrics-watch service the compose file runs unconditionally."
        ),
        evidence=[
            "docs/codebase-summary.md:40 — 'alembic/ Hand-written migrations through 0054'; 0055_memories_match_halfvec.py exists and revises 0054 (deployment-guide.md:242 correctly names 0055)",
            "docs/codebase-summary.md:178 — key-files row '`backend/app/graph/tools.py` | `TOOL_SCHEMAS` + `_dispatch_tool`'; no tools.py exists — tools live in the tools/ package and TOOL_SCHEMAS/_dispatch_tool live in graph/schemas.py:27/:269, as the same doc's module map already states — the table contradicts the map one screen above",
            "docs/codebase-summary.md:46,:200 — '13-service prod stack' enumeration omitting metrics-watch; docker-compose.yml:362-437 defines metrics-watch always-on (only oa-profile-backfill at :438-440 is profile-gated), making 14 always-on services; TECH.md:59 repeats the 13 count",
            "docs/codebase-summary.md:4 — 'Last updated: 2026-09-24'; the tools/ split, migration 0055 and metrics-watch all landed after that date",
        ],
        impact=(
            "codebase-summary.md is AGENTS.md's 'Repository map' source of truth. The phantom "
            "tools.py row sends readers to a 404 and hides the domain split; the service "
            "miscount makes `docker compose ps` (14 running) disagree with the ops docs — "
            "exactly the confusion a responder doesn't need mid-incident."
        ),
        fix=(
            "Bump :40 to 'through 0055' (or point at deployment-guide's CI-guarded HEAD line); "
            "rewrite the :178 row to graph/schemas.py and add a tools/ row naming the per-domain "
            "modules; correct :46/:200 and TECH.md:59 to 14 always-on services + the "
            "profile-gated oa-profile-backfill, adding metrics-watch to the enumeration. Refresh "
            "the 'Last updated' stamp."
        ),
        notes="Verify with `git diff HEAD -- backend/docker-compose.yml` before fixing the count: metrics-watch may be part of the uncommitted incident response (OPS-25) — if so the docs correction lands with that commit.",
    ),
]
