# Completion — TingTing verification three-try cap + gender-aware addressing

## Task record

- Task: (1) Cap `verify_tingting_identity` at three failed tries per conversation, then the fixed
  "thông tin không hợp lệ" reply + consultant handoff; the counter resets only when a human sends a
  message. (2) Improve gender classification so the bot addresses "anh"/"chị" correctly —
  deterministic inference from the name the user typed (support OA) and name-evidence guidance in
  the Jev gender question (recruitment flow).
- Scope: backend graph tools/guide/lanes/clients/schemas/ports/decisions, retrieval repository,
  tingting services, recruiter receipts, one new shared domain module, docs, tests. No schema,
  prompt-file (`app/prompts/`), webhook, or dependency changes.
- Files changed: `backend/app/services/tingting_api.py`,
  `backend/app/services/retrieval/repository.py`,
  `backend/app/services/conversation/recruiter_receipts.py`,
  `backend/app/graph/ports.py`, `backend/app/graph/tools/tingting_identity.py`,
  `backend/app/graph/tingting_guide.py`, `backend/app/graph/lanes.py`,
  `backend/app/graph/clients.py`, `backend/app/graph/schemas.py`,
  `backend/app/graph/decisions.py`, `backend/app/shared/domain/vietnamese_gender.py` (new),
  `backend/tests/test_tingting_verify_exhaustion.py` (new),
  `backend/tests/test_recruiter_reply_resets_verification.py` (new),
  `backend/tests/test_graph_runner_turn.py`,
  `backend/tests/test_runtime_surface_inventory.py` (reviewed snapshot count + digest),
  `docs/architecture/system-architecture.md`, `docs/product/codebase-summary.md`
- Instructions retrieved: `AGENTS.md`, `docs/architecture/system-architecture.md` (§14b read),
  `docs/development/code-standards.md` (boundaries respected, not re-read in full — no new
  cross-layer import outside the established graph→services / services→services directions,
  machine-checked by `test_architecture_boundaries.py`), `.claude/skills/ak-cook/SKILL.md`
- Approval required: tool-definition/behavior change (verify cap + dictated reply) — this IS the
  user-requested change (explicit instruction in-session), so approved. No alembic, no protected
  path (`config.py`, `webhooks.py`, `app/prompts/`) touched.
- Approval evidence: user messages in this session requesting the two changes and "commit all
  code and push".

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | 3 wrong submissions → dictated exhaustion reply ending in the consultant line + `needs_human` flag (`test_three_wrong_submissions_exhaust_and_flag_the_conversation`); progression asks cost nothing; verified match clears; only recruiter messages reset (`test_record_recruiter_message_resets_the_attempts`, `test_prepare_recruiter_message_resets_the_attempts`); gender line from submitted name only (`test_the_gender_line_comes_from_the_submitted_name_only`); Jev gender question now cites in-message name evidence (`decisions.py`) |
| Diff is limited to the approved scope | PASS | `git status --short` reviewed; changes limited to the files above plus the pre-existing uncommitted consultant-handoff work from the prior session (kept intact per constitution, included in the requested "commit all code and push") |
| Protected operations were avoided or approved | PASS | No alembic, no `app/prompts/`, no config/webhooks/security files, no dependency manifest changes |
| Focused tests/checks pass | PASS | `uv run pytest tests/test_tingting_verify_exhaustion.py tests/test_recruiter_reply_resets_verification.py tests/test_tingting_identity.py -q` → 23 passed |
| Broader regression tests pass when shared behavior changed | PASS | Full backend suite: 2862 passed, 1 failed → the failure was the reviewed surface-snapshot guard (`test_runtime_surface_inventory.py::test_broad_side_effect_scan_matches_reviewed_boundary_snapshot`) whose pinned `provider_boundary` count 87→89 reflects the two new Redis sites in the provider-transport `tingting_api.py` (count()'s `get`, reset()'s `delete`); count + digest + review comment updated per the file's own convention, then `pytest tests/test_runtime_surface_inventory.py -q` → 5 passed; rerun of the complete suite recorded in-session before commit |
| Lint passes for affected code | PASS | `uv run ruff check` over every changed file → "All checks passed!" |
| Type checking passes for affected code | N/A | Repo defines no type checker (Makefile gate is ruff + pytest only) |
| Build/import validation passes for affected code | PASS | Full suite imports every touched module; `pytest` collection succeeded over the repo |
| Security and privacy impact reviewed | PASS | Cap scope (`_conversation_scope`) is server-injected in `scoped_args`, never model-supplied, so the cap cannot be dodged by varying an id; gender is inferred ONLY from the employee-submitted name — a record-derived value would leak answer-key data; attempt keys are digests, never raw ids; no message content logged |
| Performance and async-I/O impact reviewed | PASS | Two Redis ops (GET/INCR+EXPIRE) on an already-tool-latency-dominated path, both fail-open; `needs_human` write is one idempotent UPDATE on the rare 3rd failure |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Fixed operator-approved Vietnamese exhaustion reply; conservative gender classifier returns "" (neutral "anh/chị") on ambiguity; tone-collision Dung/Dũng documented and pinned by tests |
| Error handling and compatibility reviewed | PASS | Store fail-open mirrors `TingtingFlowStore` (Redis outage → uncapped flow, never a lockout); port methods tolerate empty scope (legacy tests/ports without the seam); exhaustion flag is idempotent (WHERE needs_human IS FALSE) and best-effort behind the reply |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `docs/architecture/system-architecture.md` §14b + `docs/product/codebase-summary.md` updated; no routed path moved (see doc-links evidence below) |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added |
| Final `git diff --check` passes | PASS | see below |
| Final `git status --short` reviewed | PASS | see below |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: the exhaustion `needs_human` write uses the turn's session
  (committed immediately); if that commit raced a turn crash the lane suffix hook still escalates
  — defense in depth, both paths tested. The full-suite run and final git gates are recorded in
  the session transcript; the counter is Redis-only, so losing Redis re-opens the cap (fail-open
  by design, same contract as the flow store).
