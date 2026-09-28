# OPS-30 completion record — graph package Pyright baseline

Copied from `standards/agent-completion-checklist.md` per the restored
constitution's completion contract.

## Task record

- Task: OPS-30 — `backend/app/graph` ungated Pyright errors: Optional-flow
  narrowing, `DecisionTraceSummaryCode` literal drift, object-typed iteration.
- Scope: `backend/app/graph/**` plus the approved scoped extension (the
  `DecisionTraceSummaryCode` Literal in `backend/app/schemas/bot_run.py`) and
  one never-asserted fixture literal in `backend/tests/test_graph_runner_turn.py`.
- Files changed: proactive.py, clients.py, runner.py, router.py, usage.py,
  income_contract.py, provider_failover.py, tools/jobs.py, tools/income.py,
  tools/tingting_identity.py (all `backend/app/graph/`), `app/schemas/bot_run.py`
  (+4 Literal members, triaged), `tests/test_graph_runner_turn.py` (fixture
  literal `off_topic` → `off_domain_terms`, never asserted).
- Instructions retrieved: kanban card `20260928_OPS-30-*`,
  `.claude/rules/development-rules.md`, team coordination rules, plus the
  lead's mid-task scope extension (bot_run.py Literal block only).
- Approval required: no protected path touched — app/graph and schemas are not
  on the AGENTS.md approval-gated list; the card's scope extension was granted
  by the lead with triage evidence (inert compatibility sink, additive-only
  Literal members).
- Approval evidence: owner instruction of 2026-09-28 to handle all kanban TODO
  cards; lead scope-extension approval (verified the triage firsthand before
  granting).

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `uvx pyright app/graph` → 0 errors (0 warnings, 0 informations) with the new `backend/pyrightconfig.json` venv binding; was 52 live code errors. Zero `# type: ignore`/`# pyright: ignore` added. |
| Diff is limited to the approved scope | PASS | All edits inside `backend/app/graph/**`, the approved bot_run.py Literal block, and the one fixture literal. The out-of-ownership bot_run.py edit was flagged by the teammate, triaged, and approved by the lead before it landed. |
| Protected operations were avoided or approved | PASS | No migrations, webhooks, auth, bot prompt/safety text, dependencies, or deployment files touched. |
| Focused tests/checks pass | PASS | `pytest tests/test_graph_runner_turn.py tests/test_architecture_boundaries.py -p no:randomly` → 139 passed (lead re-run); teammate ran 351 graph-keyword tests plus every mandated focused suite, all green. |
| Broader regression tests pass when shared behavior changed | PASS | The schemas Literal is consumed by graph + traces; the inventory scan is provably scan-neutral (teammate's git-archive comparison), and the whole `test_runtime_surface_inventory.py` file passes after the lead's snapshot re-key. |
| Lint passes for affected code | PASS | `ruff check app/graph` and the touched test files pass (teammate; no changes since). |
| Type checking passes for affected code | PASS | pyright 0 errors for app/graph; lead re-ran both bare (via pyrightconfig) and with explicit `--pythonpath .venv/bin/python`. |
| Build/import validation passes for affected code | PASS | Import edge guard (test_architecture_boundaries.py) green; suites import the full graph package. |
| Security and privacy impact reviewed | PASS | No credential, prompt, or transport logic changed; the enum additions are inert compatibility-sink codes (record_decision is a no-op sink excluded from v2 traces). |
| Performance and async-I/O impact reviewed | PASS | Changes are annotations, narrowing, and one dead-default change (`TurnRoute.reason` `""` → `"empty"`, every constructor passes reason explicitly); no new I/O or await paths. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | Backend typing only. |
| Error handling and compatibility reviewed | PASS | Disclosed nuances: proactive.py skips profile injection silently when `deps.lead` is None (test-only misconfiguration; the warning previously logged via an incidental AttributeError path) — success path identical. |
| Documentation impact handled | PASS | No routing change; `node scripts/check-doc-links.mjs` green at HEAD. The pyright gate itself is documented by the Makefile comment. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. |
| Final `git diff --check` passes | PASS | Clean. |
| Final `git status --short` reviewed | PASS | Remaining dirty files are this task's own set plus the lead's gate files, all being committed. |

## Result

- Overall status: COMPLETE
- Remaining risks or follow-ups: the `TurnRoute.reason` Literal now constrains
  reason codes statically; lanes.py records two additional codes
  (`support_clarify`, `support_only_handoff`) through the str-typed sink
  protocol that pyright cannot see — if those ever flow into Literal-typed
  fields they will surface as new pyright errors, which is the gate working.
