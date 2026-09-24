# Agent Completion Checklist — Candidate gender inference (Jev)

## Task record

- Task: Ask the per-turn Jev fan-out the candidate's gender (from the account
  display name + the candidate's own messages) and store a confident `male`/`female`
  into a blank `leads.gender`, so the bot addresses the candidate "anh"/"chị"
  instead of the neutral "anh/chị".
- Scope: `backend/app/graph/{ports,decisions,types,factories,runner}.py`,
  `backend/app/recruitment/application/ports.py`,
  `backend/app/recruitment/infrastructure/service_adapters.py`,
  `backend/app/composition/recruitment.py`,
  `backend/app/services/lead/repository.py`, unit + integration tests, `TECH.md`.
  No schema change (reuses `leads.gender`), no dependency change, no protected file.
- Files changed: 13 modified + 1 new test file (see `git status --short`).
- Instructions retrieved: `AGENTS.md`, `docs/code-standards.md` conventions via
  neighboring code, the approved plan (`local://gender-inference-plan.md`).
- Approval required: yes — adds a judgment to the Jev turn-prompt taxonomy (bot
  prompt behavior) and changes stored candidate-data semantics.
- Approval evidence: the user approved the plan ("Plan approved.") and then
  interjected the refinement that gender is judged only from the profile name and
  the candidate's own messages (bot replies excluded), which was implemented.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Live e2e against dev DB: blank lead → Jev `female` (0.89, degraded False) → written → `address_form` `chị` → prompt contains `Gọi người dùng là 'chị'`; cleanup confirmed. Live Jev accuracy: `Nguyễn Thị Hoa`→female 0.95, `Trần Văn Hùng`→male 0.75, `Bé Gấu`→unknown 0.74. |
| Diff is limited to the approved scope | PASS | `git status --short`: only the planned modules + tests + `TECH.md`. No Alembic, deps, or protected paths. |
| Protected operations were avoided or approved | PASS | No `alembic/versions/*`, `core/{config,security,ratelimit}.py`, `api/{webhooks,dependencies}.py`, `persona.md`, Makefiles, or `.env` touched. |
| Focused tests/checks pass | PASS | `.venv/bin/pytest -m "not integration" tests/test_graph_decisions.py tests/test_graph_runner_turn.py tests/test_persona_voice.py tests/test_graph_factories.py tests/test_graph_import_guard.py` → 164 passed. Integration: `pytest -m integration tests/integration/test_lead_gender_memory.py` → 5 passed. |
| Broader regression tests pass when shared behavior changed | PASS | Full suite `.venv/bin/pytest` → 2321 passed, 42 skipped (one reviewed boundary snapshot updated: `test_runtime_surface_inventory.py`). |
| Lint passes for affected code | PASS | `.venv/bin/ruff check .` → All checks passed. |
| Type checking passes for affected code | N/A | Repo has no separate type-check gate (ruff only; no mypy/pyright config). |
| Build/import validation passes for affected code | PASS | Full pytest import + `test_graph_import_guard.py` pass; lazy imports keep the graph layer free of concrete-service imports. |
| Security and privacy impact reviewed | PASS | Gender is candidate data; the value itself is never logged (`logger.info("candidate gender inferred conversation=%s", ...)` logs only the conversation id). Lookups/writes are best-effort and swallow exceptions so they never break a turn. |
| Performance and async-I/O impact reviewed | PASS | One extra indexed read (`by_zalo_id`) and at most one blank-only `UPDATE` per turn; both awaited, timed into `timings["lead_gender"]`. The gender question adds tokens to the existing single fan-out call, not a new call. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. Vietnamese UX: neutral "anh/chị" preserved when gender is unknown; wrong address avoided by a 0.7 confidence floor. |
| Error handling and compatibility reviewed | PASS | `stored_gender`/`record_inferred_gender` failures are caught and logged; a turn still ends `sent`. New `decide_turn` kwargs are optional; `lead_gender=None` in tests/legacy skips all new work. A missing/non-canonical gender answer reads `"unknown"` and does not degrade the fan-out. |
| Documentation impact handled | PASS | `TECH.md` turn-decisions row updated to include the gender judgment and its addressing effect. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean. |
| Final `git status --short` reviewed | PASS | 13 modified + 1 new test file, all in scope. |

## Follow-up: Jev client hardening (post-plan, user-directed)

After the plan, the user directed a Jev best-practice review. Research against the
live TypeSafe docs (`docs.typesafe.ai`) and confirmed decisions with the user:

- **Bundling (Speculative Fan-Out)**: gender already rides the single `systemone`
  call — no second request. User confirmed: keep omitting the gender question when
  `leads.gender` is already set (relevance is known before the call; extra questions
  cost tokens).
- **Language**: keep Vietnamese instructions/criteria (live results strong; state is
  Vietnamese regardless). English is Jev's primary language per docs — noted, not
  changed.
- **Model**: keep the `jev-latest` alias (admin-configurable).
- **Client hardening** (`graph/decisions.py`), all doc-backed:
  - Per-request `timeout=` now passed to the httpx METHOD. `get_http_client` caches
    the process-scoped client by name and ignores a later construction timeout, so
    the previous `timeout=` at construction bounded nothing.
  - `Retry-After` / `retry-after-ms` honoured on a retryable status (SDK parity).
  - One shared per-call deadline (`JEV_CALL_TIMEOUT_S`) across attempts; the retry
    only runs when the wait fits the remaining budget.
  - Retry set aligned to the SDK default: 408, 429, and 5xx (was 429/529 only).
- Tests added (`test_graph_decisions.py`): `_retry_after_seconds` parsing,
  Retry-After honoured + per-request timeout passed, 5xx retried, non-retryable
  status not retried, retry skipped when the wait exceeds the budget.

Verification after the follow-up: focused gate 175 passed; full suite
**2326 passed, 42 skipped**; `ruff check .` clean; live Jev re-check female 0.94 /
male 0.62 / unknown 0.73, all `degraded=False`. The inventory digest was updated
again for the new `_retry_after_seconds` scope (reviewed).

Observed: run-to-run Jev variance puts a clear male name at 0.62–0.75, so a turn
below the 0.7 gate stores nothing and the next message re-judges — the intended
conservative behaviour.

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - The full async webhook e2e (`POST /webhooks/zalo/chatbot` with Redis + RQ
    workers + Jev enabled via the admin toggle) was not run; the equivalent
    real-Jev + real-DB + real-prompt path was exercised directly and the runner
    wiring is unit-tested. Enabling Jev is an admin setting, so the live webhook
    path is left to the operator.
  - A Messenger contact's stub lead is keyed by `contact_id` with NULL `zalo_id`
    (migration 0047), so on a Messenger *first* turn the write targets no row and
    the value lands on the next turn (addressing stays neutral that turn, matching
    the re-judge rule). A contact-keyed write variant would be a follow-up if
    first-turn Messenger persistence is later required.
  - `test_runtime_surface_inventory.py` counts dict `.get()` calls as
    `provider_boundary` in files carrying `get_http_client`; the three new dict
    lookups in `decide_turn` bumped that site (16→19), so the reviewed digest was
    updated with a comment. A future tightening of that heuristic would be a
    separate change.
