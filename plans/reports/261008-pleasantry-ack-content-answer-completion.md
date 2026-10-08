# Completion — pleasantry-ack fail-closed backstop (2026-10-08)

## Task record

- Task: Stop the bot from answering a content answer ("Đồng triều ạ") with a bare
  "😊". Root cause: the ack lane (`backend/app/graph/lanes.py`) trusted Jev's
  probabilistic `pleasantry` vote, which misjudged a short mid-flow answer as a
  social nicety and shipped `POLITE_ACK_REPLY` with no model run.
- Scope: ack-lane gate + Jev pleasantry question text + lexicon module + tests.
  No other lanes, no reply-copy changes, no DB or schema changes.
- Files changed:
  - `backend/app/shared/domain/politeness.py` (new) — `is_known_pleasantry`
  - `backend/app/graph/lanes.py` — ack lane gated by the lexicon; comments updated
  - `backend/app/graph/decisions.py` — pleasantry instructions now teach that a
    short answer to `bot_last_message`'s pending question is content
  - `backend/tests/test_shared_politeness.py` (new)
  - `backend/tests/test_graph_runner_turn.py` — regression test
    `test_pleasantry_ack_never_fires_on_a_content_answer`
- Instructions retrieved: `AGENTS.md` task routing (implementation standards),
  graph/decisions/lanes modules and their tests.
- Approval required: no (bug fix within the reported incident's scope).
- Approval evidence: user reported the incident directly.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Regression test replays the exact incident input: pleasantry=True + "Đồng triều ạ" → agent runs, not the smile (`tests/test_graph_runner_turn.py::test_pleasantry_ack_never_fires_on_a_content_answer`) |
| Diff is limited to the approved scope | PASS | 5 files listed above, nothing else (`git status --short` below) |
| Protected operations were avoided or approved | PASS | No commit, push, deploy, or migration |
| Focused tests/checks pass | PASS | `pytest tests/test_shared_politeness.py tests/test_graph_runner_turn.py -k "pleasantry"` → 6 passed |
| Broader regression tests pass when shared behavior changed | PASS | runner+decisions+repair+golden+tiering: 257 passed, 21 skipped (opt-in live Jev replay needs `JEV_API_KEY`); architecture boundaries: 24 passed |
| Lint passes for affected code | PASS | `ruff check` on all 5 files → all checks passed |
| Type checking passes for affected code | N/A | Repo has no mypy/pyright config in `backend/pyproject.toml` |
| Build/import validation passes for affected code | PASS | Full runner suite imports and runs: 189 passed |
| Security and privacy impact reviewed | PASS | Lexicon is a closed keyword set; no PII, no logging changes, no new external calls |
| Performance and async-I/O impact reviewed | PASS | `is_known_pleasantry` is sync, O(tokens), stdlib-only; the misjudged-content path now runs the agent (heavier than the old smile — intended: the candidate gets a real answer) |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Candidate-facing behavior: a real answer instead of a lone emoji; diacritic-insensitive matching via `normalize_vietnamese_text` |
| Error handling and compatibility reviewed | PASS | Unknown pleasantry phrasings fall through to the agent (the pre-lane behavior); Jev-degraded turns are unchanged (pleasantry=False) |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | N/A | No doc routing targets changed; module docstrings carry the incident context |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added |
| Final `git diff --check` passes | PASS | Clean |
| Final `git status --short` reviewed | PASS | Only the 5 files above |

## Result

- Overall status: PASS (code + tests). Production turn data was not reachable from
  this environment (local `bot_runs`/`messages` end 2026-09-30; the incident lives
  on prod), so the prod classification itself is CODE-READ, not DB-verified. The
  bare "😊" has exactly one emitter in the codebase (`POLITE_ACK_REPLY`), and the
  replay test reproduces the misjudgment path deterministically.
- Remaining risks or follow-ups:
  - Run the opt-in live Jev replay with the prod key before/after deploy:
    `JEV_EVAL=1 JEV_API_KEY=... pytest tests/test_golden_set.py` to measure the
    tightened pleaasanry prompt against the real classifier.
  - The lexicon backstop is intentionally conservative: an unusual pleasantry
    phrasing now runs the agent (safe direction, costs one model turn).
