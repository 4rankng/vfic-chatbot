# TingTing support OA: reset-password-only scope — completion record

## Task record

- Task: scope the TingTing support OA to the password-reset flow only — its prompt is a
  code-defined TingTing assistant (persona + embedded reset guide), never the VFIC recruitment
  persona, the active-project index or the recruiting rules; an unclear intent gets exactly one
  fixed confirm question; anything else gets exactly "Vui lòng chờ chuyên viên tư vấn liên hệ."
  plus a human handoff; other employees' data is never looked up or disclosed.
- Scope: backend prompt/routing + tests + one architecture doc bullet. No migration, no frontend
  change, no recruitment-OA / Bot / Messenger behaviour change.
- Files changed:
  - `backend/app/graph/tingting_guide.py` — `TINGTING_SUPPORT_PERSONA` (code persona),
    `TINGTING_CONFIRM_REPLY`, `TINGTING_FIELDS_ASK`, the guide's clarify bullet + step-1
    three-field ask + own-identity-only safety line, `tingting_support_system_prompt()`, `__all__`.
  - `backend/app/graph/lanes.py` — `_agent_turn` prompt branch (OA → code persona + guide),
    recruitment context appends gated off (`project_context` block, lead context,
    `forced_project_slug`), vacancy/income tool-planning flags cleared on the OA, handoff queue
    write when the model emits the handoff line, `_resolve_lane` never takes the
    clarification/direct-context lane on the OA.
  - `backend/app/graph/decisions.py` — dropped ", tra cứu thông tin nhân viên" from the
    `employee_support` intent criterion.
  - `backend/app/graph/router.py` — dropped the same phrase from the `employee_support` routing
    hint; `_SUPPORT_CLARIFY_INTENTS` comment now names the fixed confirm question.
  - `backend/tests/test_tingting_api.py` — 4 new guide/persona tests; step-1 anchor updated.
  - `backend/tests/test_graph_runner_turn.py` — 2 new OA tests (prompt substitution, handoff
    queue write).
  - `docs/architecture/system-architecture.md` §14b — routing bullet.
  - `plans/reports/260927-tingting-oa-reset-only-completion.md` — this record.
- Instructions retrieved: `AGENTS.md`, `.claude/CLAUDE.md`, `docs/architecture/system-architecture.md`
  §14b, `standards/agent-completion-checklist.md`.
- Approval required: no (in-scope implementation of the approved plan; the plan's approval gate was
  met by the operator's "Plan approved" message in this session).
- Approval evidence: operator approved the plan verbatim in-session; the plan itself is stored at
  `local://tingting-oa-reset-only-plan.md`.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Every plan step 1–7 item landed (steps 1–6 in this commit). OA prompt substitution, confirm question, three-field ask, handoff queue write and lane guards are all in `backend/app/graph/{tingting_guide,lanes,decisions,router}.py`; both fixed strings are single-source constants interpolated into the guide. |
| Diff is limited to the approved scope | PASS | `git status --short` lists exactly the 7 files above plus `.claude/CLAUDE.md` (a pre-existing local change, exempt from `release-check`, not part of this commit's change set). No migration, no frontend file, no recruitment-OA path. |
| Protected operations were avoided or approved | PASS | No DB migration, no destructive command, no deletion of unrelated code. `make deploy-backend` (operator-approved step) is the only production-touching action; production is health-probed only. |
| Focused tests/checks pass | PASS | `cd backend && .venv/bin/python -m pytest tests/test_tingting_api.py -q` → `46 passed`. `pytest tests/test_graph_runner_turn.py -q -k "tingting or support_oa or persona or system_prompt"` → `11 passed, 104 deselected`. `pytest tests/test_graph_decisions.py -q` → `29 passed`. |
| Broader regression tests pass when shared behavior changed | PASS | `cd backend && .venv/bin/python -m pytest -m "not integration" -q -p no:cacheprovider` → `2704 passed, 28 skipped, 144 deselected, 2 warnings in 136.30s`. Shared modules touched: `lanes.py`, `decisions.py`, `router.py`. |
| Lint passes for affected code | PASS | `cd backend && .venv/bin/ruff check .` → `All checks passed!` (the repo gate is `ruff check`; `ruff format` is not wired into any target and the touched files already diverge from it). |
| Type checking passes for affected code | N/A | No type checker configured or run in this repo (`backend/pyproject.toml` has no mypy/pyright config; `make lint` runs ruff + pytest only). New annotations are plain `str`/`bool`. |
| Build/import validation passes for affected code | PASS | Every test/smoke run above imports `app.graph.*` at module import; the f-string guide was additionally rendered and asserted in `/tmp/oa_scope_check.py` and in `test_tingting_api.py` (`tingting_support_system_prompt(include_guide=True)` → 7436 chars, `=False` → 1967 chars). |
| Security and privacy impact reviewed | PASS | The change *reduces* exposure: the OA loses the personnel-lookup capability text ("tra cứu thông tin nhân viên") from both the intent criterion and the routing hint, and the guide gains "CHỈ xác minh danh tính của chính người đang nhắn. KHÔNG tra cứu, không đọc ra, không xác nhận và không gợi ý thông tin của bất kỳ nhân viên nào khác". No secret enters the prompt (base URL/key still excluded); no new logging of personal data. |
| Performance and async-I/O impact reviewed | PASS | Same number of awaiting reads per OA turn (one `tingting_api_configured` read, moved earlier; `build_system_prompt` is no longer called on the OA, so a Redis cache hit + possible 2 DB reads are removed). The handoff queue write only runs on the rare exact-handoff-line reply. Full smoke (which drives the real turn services) stayed at ~5.5s for 5 probes. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change; the only user-visible text is the fixed Vietnamese confirm/handoff wording, taken verbatim from the approved plan. |
| Error handling and compatibility reviewed | PASS | The `tingting_api_configured` read keeps its `except Exception` → warning + `False` fail-closed shape inside the new branch; the handoff write reuses `_tingting_support_handoff` (best-effort, `preserve_turn_ownership=True`). Non-OA turns are byte-identical: the non-OA branch still calls `build_system_prompt` and keeps every context append (asserted in `test_support_oa_turn_uses_the_tingting_prompt_not_the_recruitment_one`). |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `node scripts/check-doc-links.mjs` → `Agent routing OK: 55 paths and 4 make targets across 5 documents all resolve.` §14b's routing bullet now states the code persona, the fixed confirm question and the model-sent-handoff queue write. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | No such markers added; `grep -rn "TODO\|FIXME\|HACK"` over the touched hunks is empty. |
| Final `git diff --check` passes | PASS | `git diff --check` → exit 0, no output. |
| Final `git status --short` reviewed | PASS | 7 modified files: the 6 changed source/test/doc files + this report; plus the exempt local `.claude/CLAUDE.md`. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  1. The OA's confirm question is model-served (the persona prescribes the exact sentence). If
     production drifts from it, the fallback is to return `TINGTING_CONFIRM_REPLY` from code in the
     `_SUPPORT_CLARIFY_INTENTS` branch before the agent call — same shape as the existing
     `TINGTING_HANDOFF_REPLY` branch. Not needed unless drift is observed.
  2. The OA's recovery hint still says "hỏi từng bước một" (about the flow steps) while the persona
     and guide now require the three identity fields in one message. The persona is the OA's system
     prompt and is authoritative; the hint is user-text-level context. Left unchanged to keep the
     diff to the approved scope — flag if the model collects fields one at a time.
  3. A non-recruitment runtime manifest (`manifest_policy.pack_key != "recruitment"`) dispatches
     through `run_manifest_composed_agent` before the new prompt branch, so such an installation
     would keep its own composed prompt. Production runs the recruitment pack, where the OA now
     reaches the code persona; the plan's scope did not cover the manifest-composed path.
  4. Production behaviour is accepted on the strength of the local gates above plus the deploy's own
     smoke gate; no live OA conversation is exercised, per the instruction that production is
     health-probed only.
