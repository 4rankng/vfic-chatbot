# Agent Completion Checklist

## Task record

- Task: `progressive-visible-boundary` — make the progressive early-bubble path
  fire when MiniMax M2 streams its deliberation inline in think tags.
- Scope: `backend/app/graph/safety.py` (think-block patterns + `visible_offset`),
  `backend/app/graph/runner.py` (`_await_first_bubble` measures the
  candidate-visible region), tests in `backend/tests/test_graph_safety.py` and
  `backend/tests/test_graph_runner_turn.py`.
- Files changed:
  - `backend/app/graph/safety.py`
  - `backend/app/graph/runner.py`
  - `backend/tests/test_graph_safety.py`
  - `backend/tests/test_graph_runner_turn.py`
  - `plans/reports/260926-1033-progressive-visible-boundary-completion.md` (this file)
  - Untouched but present in the working tree: `backend/scripts/verify_streaming_turn.py`
    (pre-existing user modification, not part of this task, not staged/committed).
- Instructions retrieved: `AGENTS.md` (auto-loaded repo rules),
  `standards/agent-completion-checklist.md`, `docs/system-architecture.md` snippet
  search (no progressive-send reference → no doc impact).
- Approval required: yes — the approved plan includes `make deploy` to production.
- Approval evidence: operator message "Plan approved." with the full plan inlined,
  which contains the "Deploy + prod proof" section.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `runner._await_first_bubble` now derives `visible_start = visible_offset(stream.raw)`, skips while deliberation is open, measures the wait cap (`len(visible)`) and the floor (`visible_start + PROGRESSIVE_BUBBLE_MIN_CHARS`) against visible text only, tests substance and grounding on `visible_bubble`, and keeps `offset`/`bubble_raw` as true `raw` offsets. `safety.visible_offset` is the single source of think-block semantics alongside `strip_think_reasoning`. |
| Diff is limited to the approved scope | PASS | `git status --short` shows only the four plan-named files modified by this task; `backend/scripts/verify_streaming_turn.py` is a pre-existing user change left untouched. |
| Protected operations were avoided or approved | PASS | No edit to `alembic/versions`, webhooks, auth, bot prompts/personas, dependencies, deployment files, `.env`, or `Makefile`s. The only protected operation is the plan-approved `make deploy` (see Result). |
| Focused tests/checks pass | PASS | `.venv/bin/pytest tests/test_graph_safety.py tests/test_graph_runner_turn.py -q` → `119 passed`. |
| Broader regression tests pass when shared behavior changed | PASS | `.venv/bin/pytest -m "not integration" -q` → `2377 passed, 24 skipped, 131 deselected, 2 warnings in 22.12s`. |
| Lint passes for affected code | PASS | `.venv/bin/ruff check app/graph/safety.py app/graph/runner.py tests/test_graph_safety.py tests/test_graph_runner_turn.py` → `All checks passed!` |
| Type checking passes for affected code | N/A | Repo has no type-check gate for these modules (no mypy/pyright config in `backend/`). |
| Build/import validation passes for affected code | PASS | The full offline suite imports `app.graph.runner` and `app.graph.safety` (2377 tests collected and run). |
| Security and privacy impact reviewed | PASS | The invariant "provider reasoning must never reach a candidate" is preserved and strengthened for the early-bubble path: the bubble text is finalized from `visible_bubble` (post-close-tag text), so no deliberation can be sent early. No new logging of message content. |
| Performance and async-I/O impact reviewed | PASS | Pure in-memory string arithmetic inside the existing `while True` loop; `visible_offset` is O(len(raw)) with three compiled regexes, no new I/O, no new task. The no-think path is byte-identical to the previous behavior (`visible_start == 0`), verified by all pre-existing progressive tests staying green unchanged. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. Vietnamese-text handling is covered by the bubble boundary/substance tests. |
| Error handling and compatibility reviewed | PASS | No public contract changed. `offset` stays an absolute `raw` offset, so `early.raw + raw[offset:] == raw` and no text is sent twice. The documented out-of-scope shape (a second *unclosed* think block after a closed one) is not handled, per plan; the finalize strip still guarantees no reasoning reaches the candidate. |
| Documentation impact handled | PASS | No doc describes the progressive wait-cap measurement (`grep -rn "progressive" docs/*.md TECH.md` → no match); the design intent in the `runner.py` comment block is unchanged. No user-visible command or contract changed. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. |
| Final `git diff --check` passes | PASS | `git diff --check` → exit 0, no output. |
| Final `git status --short` reviewed | PASS | Only the four task files plus the pre-existing `backend/scripts/verify_streaming_turn.py`. |

## Verification log

Red → green, before/after `runner.py` edit:

- RED — `.venv/bin/pytest tests/test_graph_runner_turn.py::test_progressive_inline_thinking_answer_sends_bubble_from_visible_text -q`
  → `1 failed`, `AssertionError: assert 'error' == 'sent'`, captured log
  `ERROR app.graph.runner:runner.py:1114 agent error, reply suppressed`. Root
  cause proven: the fake streamed the think block first and paused waiting for an
  early dispatch; with the wait cap measured over the raw stream (think block
  alone exceeds `PROGRESSIVE_MAX_WAIT_CHARS = 700`), `_give_up()` fired and no
  early send ever happened.
- GREEN — same test after the fix passes; targeted run `119 passed`; full offline
  suite `2377 passed`.

Plan deviations recorded (no behavior substituted):

1. `test_visible_offset_points_past_the_last_closing_tag`: the plan's literal
   (`"...SECRET...mid <think>Chào bạn!"`, second opener *unclosed*) contradicts the
   plan's own spec (`matches[-1].end()` → last *closing* tag) and its deliberate
   non-handling note. The test now uses two *closed* blocks so it asserts the
   stated "past the last closing tag" semantics; the divergence shape stays
   intentionally unhandled and un-pinned.
2. The red failure surfaces as `outcome == "error"` rather than the plan's
   predicted `len(svc.dispatched) == 1`: the paused fake waits 5 s for the early
   dispatch that never comes and the lane then raises. Same root cause, stronger
   signal (the early send is provably absent).

## Result

- Overall status: PASS — shipped to production. `531901c3` is live on
  `web-green` (previous color `blue` @ `4bbdd5e1` retained for `make rollback`).
- Deploy evidence:
  - Quality gates CI: run `36212177264`, workflow `quality-gates.yml`, commit
    `531901c3263f4ff8b234b1cc7edd1e291ad431db`, conclusion `success` (4m28s).
  - `make deploy` (repo root): local `release-check` (backend lint/unit/full
    integration, frontend lint/typecheck/unit/coverage/build/e2e desktop+mobile,
    golden RAG gate) → both images built/pushed at `:531901c3` → blue/green
    cutover. Smoke gate `SMOKE OK: outcome='sent'`; `flip_caddy` → `web-green`;
    post-flip verification green (public `/health`, frontend root, Caddy upstream,
    worker counts, `{"queue_depth": 0, "busy_workers": 1, "total_workers": 7}`).
    Old `web-blue` drained and stopped. Total 792 s.
  - Prod state: `ACTIVE_COLOR=green`, `PREV_COLOR=blue`, `PREV_TAG=4bbdd5e1`,
    `vfic-web-green-1` = `ghcr.io/4rankng/tinghire-be:531901c3`,
    `https://bot.tingting.vip/health` → `{"status":"ok","env":"production"}`.
- Production behavioral proof (plan's `bot_runs` query, 45-minute window):
  | started | outcome | lane | progressive_send | first_bubble_ms | end_to_end_ms | bubbles |
  |---|---|---|---|---|---|---|
  | 02:53:09 | SENT | agent | — | — | 17375 | — |
  | 02:52:22 | SENT | agent | true | 9500 | 13216 | 2 |
  | 02:51:06 | SENT | agent | true | 14635 | 19132 | 2 |
  | 02:43:08 and earlier | SENT | agent | — | — | ~8.7–19.0 s | — |

  The two turns after the flip (`web-green`, `531901c3`) carry
  `progressive_send=true` with `first_bubble_ms` well below `end_to_end_ms`;
  every pre-flip turn (old `4bbdd5e1`) has no stamp, matching the reported bug.
  The 02:53:09 turn formed no stamp: the lane won the race on that one (provider
  emitted its answer late), which the plan anticipates and is not a defect.
- Bubble/remainder integrity in prod (run 1239, 9500 ms bubble):
  - early bubble = message 3662 @02:52:22 (`bot_run_id` NULL, 270 chars), clean
    Vietnamese answer text, no reasoning, ending at a sentence/boundary;
  - remainder = message 3663 @02:52:34 (`bot_run_id=1239`, 153 chars) and
    `bot_runs.proposed_reply` == that body byte-for-byte; the remainder continues
    the bubble ("- Lịch kíp: …") with no repeated text.
  - Run 1238 (02:51:06): 285 chars of `proposed_reply` == remainder body.
- Reasoning-never-sent check (independent of the code path):
  no BOT message since 2026-09-01 contains a think tag (`0` rows); all-time, the
  only such row is `messages.id=736`, created **2026-07-22** — a delivered
  reasoning+answer blob from before `strip_think_reasoning` existed. It is
  already-delivered historical data (unfixable retroactively) and is unrelated to
  this change; recorded as a finding, no code or data action taken.
- Remaining risks or follow-ups:
  - Observed `first_bubble_ms` in prod is 9.5–14.6 s (design estimate was
    2.1–3.0 s): MiniMax M2 spends most of the turn inside its think block, so the
    first visible sentence still lands late. The bubble is early relative to the
    lane finishing, but the candidate-perceived benefit is smaller than designed.
    Measuring/pushing that earlier (e.g. provider think-suppression) is a
    separate, unapproved change.
  - If MiniMax emits answer deltas only at the very end, the lane can win the race
    and no stamp appears — provider behavior, not a defect; the deterministic
    proof remains the runner test.
  - `backend/scripts/verify_streaming_turn.py` carries a pre-existing unrelated
    operator modification (a `--with-tools` streamability probe). It was stashed
    for the clean-worktree release gate and restored afterwards; it is not part of
    this change and was not deployed with it.
