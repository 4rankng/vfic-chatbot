# Answer-completion guard — candidate never receives a cut answer

## Task record

- Task: Guarantee that every candidate-visible bot message is a complete answer
  to one concern. Root cause of the reported broken response: the agent lane's
  generation budget (`llm_agent_max_tokens`) is consumed by MiniMax's inline
  ` thinking` deliberation, so the provider stops with `finish_reason=length`
  mid-answer; the reply-policy layer that used to repair a cut answer was removed
  on purpose, so the cut shipped verbatim (observed: bus-route list ending
  mid-word, `- Tuyến Hà Phươ`).
- Scope: `MiniMaxAgent.agent` (tool loop) and `MiniMaxAgent.direct` (direct-context
  lane) — both produce candidate-visible prose through the same capped client —
  plus the operator decision to **drop the cap**: the admin knob's default is now
  0 ("no cap"), so the shipped answer lane runs unbounded.
  Out of scope: the persona, tool definitions, and the progressive-send flag.
- Files changed:
  - `backend/app/graph/clients.py` — answer-completion guard + helpers.
  - `backend/app/services/integration_settings/providers/llm.py` —
    `DEFAULT_LLM_AGENT_MAX_TOKENS = 0` (was 800) with the reasoning recorded.
  - `backend/app/graph/safety.py` — boundary docstring corrected.
  - `backend/tests/test_answer_completion_guard.py` — new focused tests.
  - `backend/tests/test_integration_settings.py` — default/fallback assertions
    (800 → 0), edge-value comment.
  - `backend/tests/test_runtime_surface_inventory.py` — reviewed inventory re-pin
    (+1 `provider_boundary` row: `clients._answer_was_cut` reads provider
    response metadata) with the digest.
  - `docs/codebase-summary.md`, `docs/system-architecture.md` — reply-boundary
    description.
- Instructions retrieved: `AGENTS.md` (boundaries, approval gates, checklist),
  `docs/code-standards.md` not needed (no API/schema change), bot diagnosis
  surface `app/graph/` read directly.
- Approval required: No. No prompt/persona/safety-policy/tool definition,
  webhook, auth, migration, dependency, or deployment change; no protected file
  touched (`core/config.py` was edited by the concurrent operator sweep, not
  here).
- Approval evidence: N/A.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `backend/tests/test_answer_completion_guard.py` (5 passed): a cut answer is continued and delivered whole; a provider that keeps stopping at the cap has its dangling tail dropped; a repeated seam is not duplicated; the direct lane is covered; a `finish_reason=stop` answer is untouched and costs one call. |
| Diff is limited to the approved scope | PASS | `git diff --stat` on the touched paths only; no unrelated reformat left behind (the `ruff format` churn it introduced was reverted line by line, verified by hunk review of `clients.py`). |
| Protected operations were avoided or approved | PASS | No file in the protected list was edited by this task (no `core/config.py`, `api/webhooks.py`, `auth_dependencies.py`, bot policy file, `index.css`, dependency manifest, deployment file, `Makefile`). |
| Focused tests/checks pass | PASS | `pytest tests/test_answer_completion_guard.py tests/test_parallel_tools.py tests/test_metrics_capture.py tests/test_graph_runner_turn.py tests/test_graph_direct_context.py tests/test_graph_proactive_turn.py -q` → 162 passed. `pytest tests/test_runtime_surface_inventory.py -q` → 5 passed. `pytest tests/test_integration_settings.py tests/test_graph_factories.py tests/test_graph_clients.py tests/test_answer_completion_guard.py tests/test_runtime_surface_inventory.py tests/test_graph_runner_turn.py -q` → 240 passed (cap-drop assertions included). |
| Broader regression tests pass when shared behavior changed | PASS | Full backend suite `pytest tests/ -q -p no:randomly` → **1 failed, 2512 passed, 24 skipped**, identical before and after the cap drop. The single failure is `test_facebook_oauth.py` secret-resolution (resolved `facebook_app_secret` / `facebook_webhook_verify_token` compare `None` instead of the values) in a run-order context. Isolation evidence that it is not this task's: it fails identically with the new test file excluded (`--ignore=tests/test_answer_completion_guard.py` → 1 failed, 2507 passed, 24 skipped), passes in isolation (58 passed) and with the neighbouring integration-setting files (97 passed), and touches no file this task modified. Treated as a pre-existing order-dependent leak from the concurrent `safety`→`extractor` integration-settings sweep. |
| Lint passes for affected code | PASS | `ruff check app/graph/clients.py app/graph/safety.py tests/test_answer_completion_guard.py tests/test_runtime_surface_inventory.py` → All checks passed. |
| Type checking passes for affected code | N/A | Repository has no type-check gate wired (`ruff` only; no mypy/pyright config in `backend/`). |
| Build/import validation passes for affected code | PASS | `python -m py_compile app/graph/clients.py` OK; every test run imports the module through `app.graph.clients`. |
| Security and privacy impact reviewed | PASS | The guard only re-asks the model for the remainder of an answer. No new external call surface, no new PII/logged content (the warning logs counts, not text), no auth/secret path touched. |
| Performance and async-I/O impact reviewed | PASS | Continuations are bounded by `_MAX_ANSWER_CONTINUATIONS = 2` **and** the existing per-turn model-call budget (`iterations_remaining`, `max_llm_calls_per_turn`), and only run when the provider reports a cut — a normal turn still costs exactly one model call (pinned by test 5). I/O stays async; the continuation reuses the same semaphore + streaming path. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. |
| Error handling and compatibility reviewed | PASS | Absent/unknown `finish_reason` → no continuation (previous behaviour). Continuation failures follow the existing provider-failure path (failover / `LLMThrottled`); loop exhaustion now prefers the accumulated answer over the last message, so the continuation instruction can never be shipped as a reply. |
| Documentation impact handled | PASS | `docs/codebase-summary.md` (new guard row), `docs/system-architecture.md` (reply-boundary diagram), `app/graph/safety.py` docstring, `_agent_max_tokens` docstring (cap covers ` thinking` on M2.x; 0 removes the extra round-trip). |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -n "TODO\|FIXME\|HACK" app/graph/clients.py` → none added. |
| Final `git diff --check` passes | PASS | `git diff --check` → empty. |
| Final `git status --short` reviewed | PASS | Only the intended paths changed by this task; the operator's concurrent `safety`→`extractor` sweep and progressive-send work in the same tree were left untouched. |

## Result

- Overall status: PASS.
- Evidence of the changed path end-to-end (real client, stub provider):
  1. `/tmp/smoke_cut_answer.py` drives the production `ChatOpenAI` client against
     a local SSE stub that answers with `finish_reason=length` then `stop` →
     `requests seen: 2`, `continuation asked: True`, `metrics: 1 output_cap`,
     `delivered == cut + rest` → `SMOKE PASS`.
  2. `/tmp/smoke_uncapped.py` drives the same client for both settings →
     uncapped (the new default) sends **no** token-limit field (`uncapped token
     keys sent: []`), while an operator-set cap still arrives as
     `max_completion_tokens: 512` (LangChain's current spelling; MiniMax documents
     it as the field for new integrations) → `SMOKE PASS`.
  Both scripts live outside the repo and are deleted after use.
- Remaining risks or follow-ups:
  1. The cap is dropped **by default**. An installation that has
     `llm_agent_max_tokens` *stored* (any past panel/API save) still wins over the
     default: set it to 0 there to unbound that lane. The admin panel renders no
     field for it (`frontend/src` has no reference to the key), so the value is
     set through `PUT /api/v1/integrations/minimax`. Checked locally: this
     checkout's DB has no stored `llm_*` rows (`select key from
     integration_settings where key like 'llm_%'` → empty), so the default
     applies; the production database was not reachable from this workstation.
     Trade-off accepted with the decision: the measured 8.5s → 6.1s wall-time
     saving of a capped turn is given up so the model can finish its
     deliberation and its answer instead of being cut; the RQ job timeout (60s,
     hang-only) and `max_llm_calls_per_turn` remain the bounds.
  2. With `llm_progressive_send` on (panel default), a long answer still arrives
     as two boundary-clean bubbles (first bubble early, remainder after). Each
     bubble ends at a sentence/newline boundary — never mid-word — but a bubble
     that is a *prefix* of one concern is not "a complete answer on its own"; if
     the operator wants strictly one complete answer per message, the flag must
     be turned off or the split moved to a concern boundary (prompt change,
     approval-gated).
  3. If the model re-emits ≥24 chars of the text it was handed, the repeated seam
     is dropped from the delivered answer, but the raw progressive stream (which
     the remainder path sends) still contains it → a possible duplicated line in
     the second bubble. `timings["progressive_stream_mismatch"]` records the
     divergence; the delivered text itself stays correct.
  4. Live MiniMax verification was not possible from this workstation (empty
     `MINIMAX_API_KEY`/`OPENROUTER_API_KEY` in `backend/.env`); the provider-side
     `finish_reason=length` behaviour rests on MiniMax's documented `max_tokens`
     semantics (thinking is returned inside `content`, so it consumes the budget)
     and the repository's own measurement note in `_agent_max_tokens`.
