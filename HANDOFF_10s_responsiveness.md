# HANDOFF — 10-second perceived-responsiveness for the Zalo OA chatbot turn

**Plan (approved v5.1, source of truth):** `/Users/dev/.claude/plans/go-through-the-whole-parallel-bee.md`
**Goal:** OA users get immediate visible activity + a reasonable human-like answer within ~10s; never wait silently past 10s. 5 slices + Step 0.

> **STATUS UPDATE — 2026-07-09.** Picked up by a fresh session after the
> original hand-off. Slices **A, B done** (prior session). **D, E.1, E.2, F.1
> now DONE & committed** in this session (commits `687d6137` for A/B/D + an
> unrelated FAQ-bypass feature that was interleaved in the same files, and
> `a3ebdfd1` for E.1/E.2/F.1). Full backend suite **491 passed / 18 skipped**.
> **REMAINING:** Slice **C** (parallel pre-work + deadline-aware skip + hot-path
> no-bind + route caps — most invasive, flag-gated), Slice **E.3** (OA httpx
> pooling — concurrent-edited `zalo_oa_service.py`), Slice **E.4** (`safety_llm_enabled`
> flag — breaks `test_safety_verdict_safe_overrides_with_final_answer`, repurpose),
> Slice **G** (per-turn stage metrics), and **Step 8** (full-suite + code-reviewer +
> lint + explicit-path commit). The co-edit tangle that blocked isolation is
> **resolved** — runner.py/types.py/config.py/safety.py are now clean in the
> working tree, so the remaining slices will stage cleanly. Original slice detail
> below is preserved for reference; the "Remaining for Slice D" and E.1/E.2/F.1
> sections are now historical (done).


---

## ⚠️ CRITICAL CONSTRAINTS (read first — these bite)

1. **Shared working tree — NEVER `git add -A`.** A concurrent Zalo/architecture-audit session edits the same files. Stage only the explicit paths you change (`git add backend/app/graph/runner.py …`). The concurrent session refactored `zalo_oa_service.py` / `zalo_bot_service.py` mid-work; expect unrelated hunks in those files.
2. **Dev Redis = port 6382** (NOT 6379/6380). Postgres on host :5432. **Always `cd backend` first.** Venv at `backend/.venv` (whitelisted in `.ckignore`).
   - Test cmd: `cd /Users/dev/Documents/projects/vfic-ats/ChatBot/backend && REDIS_URL=redis://localhost:6382/0 APP_ENV=development .venv/bin/python -m pytest <path> -q --tb=short`
3. **Persona voice invariant (persona.md:40, non-negotiable):** every bot-visible string uses **tôi/bạn**, **NEVER em/anh/chị** as address pronouns. Applies to LLM output (already bound via AGENT_SYSTEM_PROMPT) AND all hardcoded constants/templates. The drift risk is the hand-authored constants.
4. **No fake data.** Do NOT hardcode factual KB answers (salary/contacts/shuttle/location) into fast-lane templates — those must stay RAG-grounded. Only non-factual traffic (greetings/thanks/goodbye/help) is templated.
5. **Do NOT touch:** `minimax_digest_timeout` (180s, separate worker), `bot_lock_ttl_seconds` (180s). These are load-bearing for the background digest + per-chat mutex.
6. **Existing test that WILL break under Slice E:** `tests/test_graph_runner_turn.py::test_safety_verdict_safe_overrides_with_final_answer` — it relies on the LLM safety judge running. Under `safety_llm_enabled=False` (Slice E) it must be repurposed to assert the legacy verdict-override holds when the flag is True.
7. Baseline before your work: **424 tests passing**. Keep it ≥424 (growing) at every commit point.

---

## ✅ DONE & verified (do NOT redo)

### Slice A — Deadline spine (10s propagated backstop)
Files: `app/graph/types.py` (`BotRunState.received_at_epoch` + `deadline_at_epoch`), `app/services/webhook.py` (stamps `received_at_epoch`), `app/workers/chatbot_worker.py` (builds state w/ deadline), `app/core/config.py` (`sla_seconds=10.0`, `agent_max_seconds=8.5`, `send_margin_seconds=1.0`, `soft_fallback_remaining=2.0`), `app/graph/prompts.py` (`TIMEOUT_REPLY`), `app/graph/runner.py` (`_remaining()`, agent `asyncio.wait_for`, `_finish_terminal_reply()`).
Tests green: `test_expired_deadline_skips_agent_and_sends_timeout`, `test_agent_oversleep_hits_deadline_timeout`.

### Slice B — Active status signal (typing + slow-case ack)
Files: `config.py` (`typing_heartbeat_seconds=3.5`, `slow_ack_seconds=1.5`, `min_llm_time_budget=3.0`), `prompts.py` (`SLOW_ACK_REPLY`), `runner.py` (`_status_heartbeat` replaces `_typing_heartbeat`; `_cancel_status_task`; `status_task` created in `run_turn` and cancelled before every real send + threaded into `_finish_terminal_reply(status_task=...)`; `webhook.py` doc comments updated).
Tests green (11/11 in `test_graph_runner_turn.py`): `test_slow_turn_sends_one_slow_ack_then_real_answer`, `test_fast_turn_sends_no_slow_ack`. Broader 43 (graph+safety+factories+webhooks) green.

---

## 🟡 IN-PROGRESS — Slice D: FAQ fast lane (finish the test, then run)

**Already done:** `app/graph/fast_lane.py` CREATED (deterministic greeting/thanks/goodbye/help router → tôi/bạn templates; factual queries return `None` → fall through). `config.py` flag `faq_fast_lane_enabled: bool = True` added. `runner.py` import + fast-lane branch wired: the agent+safety block is now inside an `else`; `fast_lane.match()` short-circuits to `candidate=fast.reply`, `outcome_label="faq_cache"`, skips LLM safety + persist; shared pre_send_guard→send→return `{"outcome": outcome_label}`. Tests: `_state()` changed to `user_text="tôi muốn tìm việc lái xe"` (non-greeting, exercises agent path); persisted assertion updated to match.

**Remaining for Slice D:**
1. **Add the fast-lane integration test** to `tests/test_graph_runner_turn.py` (append after `test_fast_turn_sends_no_slow_ack`). The edit was rejected mid-write; this is the exact test:
```python
@pytest.mark.asyncio
async def test_greeting_hits_fast_lane_no_llm_no_ack_no_persist(monkeypatch):
    """A pure greeting is answered by the fast lane: GREETING_REPLY, outcome=faq_cache,
    the agent is never called, no slow-case ack fires, and no candidate extraction runs."""
    from app.graph.fast_lane import GREETING_REPLY

    async def _must_not_run(state, deps, user_text, *, chat_id, recent_messages):
        raise AssertionError("agent must not be called for a fast-lane greeting")
    monkeypatch.setattr(runner, "_agent_turn", _must_not_run)

    conv = _FakeConv()
    svc, _ = _stub_svc(conv=conv, owned=True)
    persisted: list[dict] = []
    zalo = _FakeZalo()

    state = BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text="chào bạn")
    res = await run_turn(state, _deps(zalo, conversation=svc, persist=persisted.append))

    assert res["outcome"] == "faq_cache"
    assert res["reply"] == GREETING_REPLY
    assert zalo.sent == [("z1", GREETING_REPLY)]
    assert SLOW_ACK_REPLY not in [text for _, text in zalo.sent]
    assert persisted == []
```
2. **(Recommended) add a pure unit test file** `tests/test_fast_lane.py` asserting `match()` for: `"hi"`,`"Chào bạn!"`,`"XIN CHÀO"`,`"cảm ơn bạn nhe"`→thanks, `"tạm biệt"`→goodbye, `"bạn giúp gì được"`→help, and `"lương bao nhiêu"`,`"tôi muốn lái xe"`,`""`→`None`. Assert every returned `.reply` contains tôi/bạn and no em/anh/chị (feeds Slice F).
3. **Run:** `cd backend && REDIS_URL=redis://localhost:6382/0 APP_ENV=development .venv/bin/python -m pytest tests/test_graph_runner_turn.py tests/test_fast_lane.py -q --tb=short` → expect all green. Then mark Slice D done.

**Acceptance for D:** greeting → `outcome="faq_cache"`, agent never called, no ack, no persist; factual query → falls through to agent (existing tests cover this via `_state()`).

---

## ⬜ PENDING — Slice E: Safety gate + blocklist + semaphore + httpx pooling

Plan Priority #4. Four sub-parts; do the additive ones first, the flag-gated safety change last.

**E.1 Blocklist (additive, safe).** In `app/graph/safety.py` add a synchronous lexical blocklist regex (profanity / sexual / self-harm / violence / politics / prompt-injection markers) and a `blocklist_hit(raw) -> bool`. In `runner.py` fast-safety section, after `fast_safety_filter`, if `blocklist_hit(raw)` → `candidate = retry_exhausted_fallback(state.user_text)` and skip the LLM safety judge. Resolve filter flags deterministically (empty→`FALLBACK_REPLY`; too-long→truncate ~1800 at word boundary; blocklist→redirect). New tests in `tests/test_graph_safety.py`.

**E.2 Semaphore micro-wait fail-fast.** `app/graph/llm_semaphore.py`: `BLPOP(self._key, timeout=30)` → read `settings.llm_acquire_timeout_seconds` (add to config, default `1.5`); on `result is None` raise `LLMThrottled` instead of proceeding degraded (worker already sends `DEGRADATION_REPLY` + clears mutex on `LLMThrottled`). `config.py`: `llm_concurrency_limit: int = 4 → 8`, add `llm_acquire_timeout_seconds: float = 1.5`, `llm_429_retry_sleep_seconds: float = 0.5`. `clients.py::_llm_call_with_retry`: the `2.0 + random.uniform(-0.5, 0.5)` 429-sleep → `settings.llm_429_retry_sleep_seconds`. **Caution:** existing `tests/test_llm_semaphore.py` asserts the degraded-proceed behavior on 30s timeout — update it to expect `LLMThrottled`.

**E.3 httpx pooling for OA.** `app/services/zalo_oa_service.py`: replace per-call `async with httpx.AsyncClient(...)` in `_post`/`_get` with a process-level pooled client (connect ~0.4s, read ~0.9s, write ~0.5s). Token-refresh (`_post_with_refresh`) must stay correct. The concurrent session edited this file — reconcile carefully, explicit `git add` only.

**E.4 Safety LLM gate (flag-gated, breaks one test).** `config.py`: add `safety_llm_enabled: bool = True`. `runner.py`: wrap the `if fs["needs_llm_safety"]:` judge+retry-regenerate block in `if settings.safety_llm_enabled:` — when False, NO LLM safety judge, NO auto-regenerate (the time bomb: ~13 calls/180s). On an unsafe fast-filter flag with the judge disabled, resolve deterministically (blocklist→redirect; overlong→truncate; empty→`FALLBACK_REPLY`). **Repurpose** `test_safety_verdict_safe_overrides_with_final_answer` to run under `safety_llm_enabled=True` (legacy verdict-override still holds). Add a test that with `safety_llm_enabled=False` the judge is never called.

---

## ⬜ PENDING — Slice C: Hot-path bounding (1 synthesis call, route caps, deadline-aware skip, parallel pre-work)

Plan Priority #3. **The deadline (Slice A) already bounds wall-clock**; Slice C tightens the P95 tail and removes the `clients.py:325` raw-ToolMessage hazard. Most invasive slice — do behind config flags so existing tests stay green.

**C.1 Parallel pre-work (low risk, do first).** `runner.py::_agent_turn`: `await build_system_prompt(...)` then `await deps.lead.context(...)` are sequential — wrap in `asyncio.gather`. System-prompt failure must propagate; lead failure swallowed (already is). New test: `build_system_prompt` raises → propagates; lead raises → swallowed.

**C.2 Deadline-aware LLM skip.** Before the synthesis call in `runner.py`: `if _remaining(state) < settings.send_margin_seconds + settings.min_llm_time_budget: skip LLM → send human fallback (GENERIC_FALLBACK / TIMEOUT_REPLY)`. New test: low remaining before LLM → no LLM call, fallback sent.

**C.3 Hot-path no-bind mode + route caps (invasive — flag-gate).** `config.py`: `hot_path_max_llm_calls=1`, `complex_agent_max_llm_calls=3`, `complex_agent_enabled_for_auto_zalo=false`, `normal_answer_max_tokens≈256`, `direct_rag_max_tokens≈192`, `llm_tool_routing_max_tokens=80`, `llm_synthesis_max_tokens=350`. `clients.py::MiniMaxAgent.agent`: add a `hot_path` mode that does NOT `bind_tools` (uses `self.llm` directly) → with no tools bound, `tool_calls` is None → returns `ai.content` on iteration 1 → exactly one synthesis call. Thread `max_tokens` per route. Gate no-bind behind `not settings.complex_agent_enabled_for_auto_zalo`. **Caution:** `tests/test_graph_clients.py` and `test_graph_factories.py` assert tools are always bound / `max_llm_calls_per_turn=6` — update or add flag=True legacy variants. `max_llm_calls_per_turn` default stays 6 (complex mode); hot path uses `hot_path_max_llm_calls=1`.

---

## ⬜ PENDING — Slice F: Persona-voice invariant guard + warm fallbacks

**F.1 Guard test (cheap, high-value).** New test (e.g. `tests/test_persona_voice.py`) importing every static reply constant — `ERROR_REPLY`, `FALLBACK_REPLY`, `TECHNICAL_FALLBACK`, `GENERIC_FALLBACK` (safety.py), `DEGRADATION_REPLY` (chatbot_worker.py), `SLOW_ACK_REPLY`, `TIMEOUT_REPLY` (prompts.py) — + every fast_lane template (`GREETING_REPLY`, `THANKS_REPLY`, `GOODBYE_REPLY`, `HELP_REPLY`). Assert each uses tôi/bạn address and contains **no "em"/"anh"/"chị" as address pronouns**. Match on word boundaries (avoid false positives: "xem","gửi","chính" are fine). This is plan test #14.
**F.2 Warm fallbacks.** Verify `TIMEOUT_REPLY` / `DEGRADATION_REPLY` are warm & apologetic (they already are — quick check). Optionally enrich TIMEOUT_REPLY with a handoff (ask for phone/area) — keep tôi/bạn. Single source in `prompts.py`/`safety.py`.

---

## ⬜ PENDING — Slice G: Per-turn stage metrics

Plan Priority #5.2. Structured per-turn record: `webhook_ack_ms`, `queue_wait_ms` (= worker_start − received_at_epoch), `prompt_build_ms`, `retrieval_ms`, `llm_ttlb_ms`, `llm_tokens_in/out`, `zalo_send_ms`, `turn_total_ms`, `ack_sent`, `outcome ∈ {real_answer/sent, faq_cache, timeout, degraded, throttled, error, suppressed}`. Sink = JSON log line + Redis counters `slo:outcome:{kind}`. Emit from `runner.run_turn` (stage timestamps) + `chatbot_worker._run_job_async` (queue_wait). New test: metrics record has correct `outcome` label, `ack_sent`, non-negative stages. TTFT split (needs streaming) + Prometheus → explicitly out of scope.

---

## ⬜ Step 8 — Finalize (mandatory)

1. **Full suite green:** `cd backend && REDIS_URL=redis://localhost:6382/0 APP_ENV=development .venv/bin/python -m pytest -q --tb=short` → expect ≥424 passing, 0 failing. Fix every regression; do not weaken tests.
2. **Code review:** spawn `code-reviewer` subagent over all changed files with acceptance criteria + the persona invariant + the no-side-effects gate. Address findings.
3. **Lint/type:** `ruff check` on changed files; mypy/pyright if configured.
4. **Commit (explicit paths only, conventional format, no AI refs):** stage only the files YOU changed — e.g. `git add backend/app/graph/runner.py backend/app/graph/fast_lane.py backend/app/graph/safety.py backend/app/graph/llm_semaphore.py backend/app/graph/clients.py backend/app/graph/prompts.py backend/app/core/config.py backend/app/services/zalo_oa_service.py backend/tests/...`. **Verify `git status` first** to avoid sweeping the concurrent session's hunks. Do NOT push unless asked.
5. **Live calibration notes:** document the Step-0 open items (read `llm:invoke_total_ms`/count + decode speed from Redis; derive queue_wait from `chat_turn_start` + `received_at`; sample ~50 OA convos for FAQ volume; confirm OA-typing docs question). These calibrate caps but are not blockers for shipping.

---

## Files touched so far (for `git status` reconciliation)
`backend/app/graph/types.py`, `backend/app/graph/runner.py`, `backend/app/graph/prompts.py`, `backend/app/graph/fast_lane.py` (new), `backend/app/core/config.py`, `backend/app/services/webhook.py`, `backend/app/workers/chatbot_worker.py`, `backend/tests/test_graph_runner_turn.py`. (`zalo_oa_service.py`/`zalo_bot_service.py` also have concurrent-session hunks — leave those alone unless your slice explicitly edits them.)
