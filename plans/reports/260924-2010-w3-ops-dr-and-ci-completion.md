# Completion Checklist — w3-ops DR trio + CI lane

## Task record

- Task: Implement kanban OPS-01, OPS-02, OPS-03, TEST-01 (wave 3 ops/test lane)
- Scope: droplet backup/restore pair correctness, restore tag/schema pinning, sealing-key transport + verification, full integration suite in the deploy gate and CI
- Files changed: `scripts/backup-droplet.sh`, `scripts/restore-droplet.sh`, `backend/scripts/verify_integration_secrets.py` (new), root `Makefile`, `.github/workflows/quality-gates.yml`, `docs/deployment-guide.md`
- Instructions retrieved: `AGENTS.md`, `docs/deployment-guide.md` (in full, per its deployment section), the four kanban tickets, `backend/tests/integration/conftest.py`, `backend/scripts/{widen_alembic_version,flip_caddy,prod-env}.sh/py`, `backend/docker-compose.yml`, `backend/app/models/integration.py`, `backend/app/services/integration_settings.py` (cipher section)
- Approval required: deploy/backup/restore path changes, CI workflow change, docs update
- Approval evidence: lead's wave-3 brief — "The user has APPROVED these gated changes; work from the tickets' evidence"

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Four commits: `98700969` (OPS-01), `750c0572` (OPS-02), `bc069298` (OPS-03), `5f8e2378` (TEST-01); validation matrix in `plans/reports/w3-ops-260924-1748-dr-and-ci-lane.md` |
| Diff is limited to the approved scope | PASS | Per-commit `git show --stat` contains only owned files; one disclosed exception: `bc069298` carries the concurrent lane's already-in-tree Makefile hardening (message discloses it; lead informed pre-commit) |
| Protected operations were avoided or approved | PASS | No deploy/push/droplet access; `backend/docker-compose.yml` (incl. REDIS_PASSWORD), `core/*`, `api/*`, `alembic/**`, `frontend/src`, `kanban/` untouched |
| Focused tests/checks pass | PASS | `bash -n` both scripts (every state); restore `--dry-run` matrix (template render, 3 refusal shapes exit 2, tag fallback precedence, 9-step plan); probe positive/negative/cleanup vs dev DB (rc 0/1/0); `make -n` for backup/restore/backup-full/release-check; workflow `yaml.safe_load` OK |
| Broader regression tests pass when shared behavior changed | PASS | `cd backend && .venv/bin/pytest -m integration --durations=25` → 116 passed, 2479 deselected, 39.38 s (shared working tree incl. other lanes' edits) |
| Lint passes for affected code | PASS | `.venv/bin/ruff check scripts/verify_integration_secrets.py` → all checks passed; shell/Make/YAML have no repo lint target (N/A beyond parse checks) |
| Type checking passes for affected code | N/A | No type-check target covers ops shell scripts or the sync probe; probe is exercised directly instead |
| Build/import validation passes for affected code | PASS | `py_compile` + real module execution of the probe inside the backend venv; probe also imported through `python -m` as `make restore` invokes it |
| Security and privacy impact reviewed | PASS | Probe prints counts + row key names, never values; env copies chmod 600; no key material or passwords logged; refusal paths fail closed |
| Performance and async-I/O impact reviewed | N/A | One-shot ops scripts; sync DB probe matches the `widen_alembic_version` precedent; no request-path code touched |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI changes |
| Error handling and compatibility reviewed | PASS | Every new failure mode fails loudly (refusals exit 2, schema/tag/decrypt mismatches exit 1) instead of the previous silent paths; dry-run remains fully local |
| Documentation impact handled | PASS | `docs/deployment-guide.md` §3/§8/§10 updated; every claim re-verified against final script text after a later docs commit by another lane |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | grep across the three scripts → none |
| Final `git diff --check` passes | PASS | `git show --check` clean on all four commits |
| Final `git status --short` reviewed | PASS | Owned paths clean; remaining dirt belongs to other lanes (ingestion deletions, docs hunks, registry work) |

## Result

- Overall status: DONE_WITH_CONCERNS
- Remaining risks or follow-ups: no real-droplet rehearsal (forbidden this wave — needs an approved window, then record the date in the runbook); `docs/DROPLET-BACKUP-RESTORE.md` drifts from the scripts and rides backups as `README-RESTORE.md`; runtime `InvalidTag` warn-and-fallback in `integration_settings.py` unchanged (out of ownership); droplet-side tag-drift guard belongs to the OPS-10 lane; `vfic_env_*.env` files are never pruned by `make backup` (key retention decision pending). Full detail in `plans/reports/w3-ops-260924-1748-dr-and-ci-lane.md`.

## Addendum — extended scope (OPS-07, OPS-18, OPS-19, TEST-06)

- Task: lead-appended tickets — pre-migration dump + migration lock bounds (OPS-07), dev bootstrap + docs (OPS-18), dead PORT plumbing (OPS-19), dependency/security scanning in CI (TEST-06)
- Files changed: `backend/scripts/bg_deploy.sh`, `backend/alembic/env.py`, `.github/dependabot.yml` (new), `.github/workflows/quality-gates.yml`, `docs/deployment-guide.md` §3
- Commits: `28626ffe` (OPS-07), `543aabd8` (TEST-06), plus two sweep-docs-routed follow-ups — `feb38b13` (release-check/CI assertion that the deployment guide names the current alembic head; validated positive and negative) and `4b2bf20a` (droplet restore load switched to ON_ERROR_STOP=1 fail-fast after a live comparison proved the old rc-gate blind to mid-script errors) and `42c89829` (semantic Makefile audit: uv-gate failure masking, FORCE message inversion, pg_restore --exit-on-error, comment truthfulness); OPS-18/19 verified already complete via `29446018` + `c37ef6a5`, no new commits
- Boundary note: `backend/alembic/env.py` is under `alembic/`, which the original brief excluded — the ticket's approved fix names it explicitly and the AGENTS.md approval gate covers only `alembic/versions/*.py`; flagged to the lead in the wave report
- Validation: `bash -n` bg_deploy.sh; ruff + py_compile env.py; full `alembic upgrade head` on a scratch DB through the new bounded connect args (to head, `0054`); `SHOW lock_timeout`/`statement_timeout` read back as `5s`/`15min`; both YAML files parse; workflow diff contains only the new job; `make -n bootstrap`/`dev` confirm the OPS-18/19 wiring; scratch DB dropped after use
- Overall status (extended scope): DONE — OPS-07 and TEST-06 implemented and validated; OPS-18/19 verified complete without rework
- Remaining risks or follow-ups: the migration timeouts take effect from the next image build onward (the deploy runner uses the freshly pulled image); dependabot pip-ecosystem PRs bump `pyproject.toml` while the real lockfile is `uv.lock` — lockfile regeneration on dependabot PRs needs a one-time check when the first such PR arrives
