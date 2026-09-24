# sweep-close — CI-green close-out (run 36015028711)

Date: 2026-09-24 (Asia/Singapore) · Branch: main · Agent: sweep-close

## Outcome

Main is green locally across every lane after the six original fixes plus the
lead's extended grants. Backend unit lane: **2300 passed, 24 skipped, 0
failed**. Backend integration lane: **131 passed**. Boundary matrix: **18/18**.
Frontend: lint, typecheck, registry:check (250 files), and vitest (110 files /
593 tests, screenshot baselines included) all clean. ruff clean. Five commits
by me (cb8ef25b, 7e33907f, e3d8c296, 36183302, fd4d75da); fixes 1–2 plus the
conftest guard landed in 11d03d2b committed by another actor, verified and
adopted. The only untested surface is the workflow YAML itself, which only a
real Actions run can execute — the next pushed CI run is its validator.

## Per-fix outcomes

**Fix 1 — installation fingerprint patch targets (in 11d03d2b, no commit by
me).** The ARCH-16 split left the test patching `service.py`, but the helpers
are defined in `runtime.py` and bound/called in `lifecycle.py`
(`get_cached_fingerprint` lifecycle.py:139, `invalidate_installation_cache`
lifecycle.py:373; `require_active` → `resolve_active` resolves both from
lifecycle.py globals). Retargeting to `app.services.installation.lifecycle`
matches the perf-retrieval precedent and the package convention (service.py
`__all__` carries only service types, so no re-export seam exists). Verified
before that commit appeared: 10 passed across both retargeted files.

**Fix 2 — lexical matcher via the document repository (in 11d03d2b, no commit
by me).** `RetrievalRepository` composes `self._documents = DocumentRepository(db)`
(repository.py:60); `_match_document_lexical_rows` is defined on DocumentRepository
(document_repository.py:261). Verified in the same 10-test run.

**Fix 4 — graph factory tests under no real credentials — cb8ef25b.** Both
tests patched `app.graph.factories._chat_for_role`, but the agent LLM is
constructed in `client_cache.py` (imports `_chat_for_role` from clients.py and
calls it at client_cache.py:152); the factories binding only serves
`_build_fast_llm`. Instead of the lead's setenv example I used the file's own
precedented pattern: `reset_client_cache()` before/after plus `get_settings`
faked in all three binding modules (factories, client_cache, clients) with
`_Settings` (`minimax_api_key = "sk-mm-fake"`). Bare setenv is order-fragile
because `get_settings()` is `@lru_cache`d with no cache-clearing autouse
fixture in tests/conftest.py. No production change. Verified with
MINIMAX_API_KEY unset: 2/2 standalone, 42/42 file-wide.

**Fix 5 — integration marker — 7e33907f.** The migration test is DB-free
(stubbed alembic ops) but unit-lane collection of a file under
`tests/integration/` loads that conftest, whose autouse fixtures request
`integration_database` and fail closed without the dev DB — the exact CI
error. `pytestmark = pytest.mark.integration` deselects it from
`-m "not integration"` (verified "1 deselected") and it passes in the
integration lane.

**Fix 3 — browser-IO + layer boundaries, redesigned as relocation — e3d8c296.**
The lead's prescribed parameter-injection shape provably could not work: these
are React hooks, and under `ALLOWED_EDGES = frozenset()` (zero-tolerance) the
imports application → react/ra-core/apiClient/project-knowledge-service are
themselves `frontend_feature_application_outward` violations. The repo's own
convention places React hooks in presentation (frontend AGENTS.md layering;
conversations already layered this way). The three hooks moved 100%-rename
unchanged to `projects/presentation/`, three callers repointed, registry.json
regenerated (its glob covers presentation/, hooks remain published; diff is
exactly the three path moves). Behavior identical by construction; confirmed by
the panel screenshot specs in the 593-test runs.

**Grant 2 — the 8 out-of-ownership edges — 36183302.** Per-edge decisions:

- *Edges 2+3 (real fix, no ledger entry):* `use-conversation-actions.ts` and
  `ChatThread.tsx` over-typed the ra-core provider handle with the concrete
  `CrmDataProvider`. The application layer already owned narrow ports
  (`ConversationModeWriter`, `MarkConversationReadPort`, `SendConversationReplyPort`,
  `RetryConversationReplyPort`), so the handles are now typed
  `useDataProvider<DataProvider & ConversationModeWriter>()` and
  `useDataProvider<DataProvider & MarkConversationReadPort & SendConversationReplyPort & RetryConversationReplyPort>()` —
  types-only change, zero runtime delta, and the concrete-provider import is
  gone from presentation. One iteration: ra-core exports `DataProvider`, not
  `DataDataProvider` (caught by typecheck).
- *Edge 1 (real fix, no ledger entry):* `conversation-presentation.ts` builds
  display view-models (display names, avatar CSS variables, search text) but
  sat in `domain/`. No recorded decision (checked the conversation-state-split
  plan) places it there, and its name says presentation. Moved 100%-rename to
  `conversations/presentation/`, two consumers repointed. The domain edge into
  capabilities/types disappears because the importing module left domain.
- *Projects hooks (mechanical):* `use-discovery-card-draft.ts` and
  `use-faq-auto-sync-notice.ts` moved 100%-rename to `projects/presentation/`,
  ProjectKnowledgePanel and DiscoveryCardEditor repointed.
- Every edge got a real fix, so nothing was added to the reviewed-inventory
  ledger; `ALLOWED_EDGES` remains honestly empty. registry.json regenerated
  once for the three path moves in this commit (one commit for the whole
  8-edge grant because the registry manifest cannot be split across commits;
  both facets — conversations rewire and projects moves — belong to the same
  granted fix).

**Grant 3 — workflow repairs — fd4d75da.** backend-unit now has setup-node 22
(npm cache against frontend/package-lock.json) plus `npm ci` in frontend/
before the unit step, so `typescript_import_scanner.cjs` (which requires
`frontend/node_modules/typescript`) can run there; this is what makes the four
scanner-based boundary tests meaningful in CI and what hid the 19-edge list
from CI logs all along. The advisory dependency-audit job's install line had
`pip-audit` glued onto `uv sync` (the e37df5c1 casualty) — repaired to
`uv sync --all-extras --frozen` + `uv pip install --python .venv/bin/python
pip-audit` so `.venv/bin/pip-audit --strict` resolves again. Verified by YAML
parse (all seven jobs, steps intact) and full diff review; only these lines
touched, per grant. Local `npm ci`+scanner equivalence is proven by the local
boundary runs, which run the same scanner against local node_modules.

**Grant 4 — the foreign conftest guard: already committed, verified, adopted.**
The autouse `_restore_head_after_schema_tests` guard landed in 11d03d2b
together with fixes 1–2 (committed by the other actor), so there is nothing
new to commit. It is correct and exercised: the full 131-test integration lane
ran green with the guard active, and it structurally protects the shared-DB
invariant fix 1 depends on.

**Grant 5 — acknowledged** (fix 4 approach approved; see above).

## Verification counts

- Backend unit lane (`env -u MINIMAX_API_KEY pytest -m "not integration" -q`):
  **2300 passed, 24 skipped, 0 failed** in 20s.
- Backend integration lane (`pytest -m integration -q`): **131 passed** in
  102.9s.
- Boundary matrix (`pytest tests/test_architecture_boundaries.py -q`): **18/18
  passed**.
- Frontend: lint clean, typecheck clean (after one caught iteration:
  `DataProvider` not `DataDataProvider`), registry:check 250 files OK, vitest
  110 files / 593 tests passed (both post-final-edit runs).
- ruff clean.

## Residual risks / notes

1. The workflow change can only be fully proven by a real Actions run; the
   next pushed CI run is its validator. All inputs it needs (node_modules for
   the scanner, clean YAML) are verified locally.
2. The advisory pip-audit repair keeps the job `continue-on-error`, so it
   stays advisory by design.
3. All five file moves are 100% renames; the two conversations edits are
   type-level only. Screenshot baselines pass unchanged.

Status: DONE
Summary: All six originally diagnosed CI issues plus all extended grants are
fixed and verified — five commits by me (cb8ef25b, 7e33907f, e3d8c296,
36183302, fd4d75da) with fixes 1–2 and the conftest guard in 11d03d2b from the
other actor; unit lane 2300 green, integration lane 131 green, boundary matrix
18/18, frontend fully green, ruff clean; every edge resolved with a real fix
so the boundary allowlist stays empty.
Concerns: none blocking; the workflow YAML awaits CI validation on the next
push, which only Actions can perform.
