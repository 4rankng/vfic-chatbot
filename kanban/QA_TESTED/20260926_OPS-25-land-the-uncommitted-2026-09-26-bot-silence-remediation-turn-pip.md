---
id: OPS-25
title: "Land the uncommitted 2026-09-26 bot-silence remediation (turn_pipeline_check gate + deploy wiring)"
severity: high
area: ops
labels: [ops, incident-followup, git-hygiene]
effort: S
status: landed
column: QA_TESTED
opened: 2026-09-26
---

# OPS-25 — Land the uncommitted 2026-09-26 bot-silence remediation (turn_pipeline_check gate + deploy wiring)

**Severity:** high · **Area:** ops · **Effort:** S · **Labels:** ops, incident-followup, git-hygiene

**Trạng thái:** LANDED 2026-09-27 — remediation set is tracked; only the image cut remains, and that is a deploy action

## Landing verification (2026-09-27)

Re-verified every item the card listed as "untracked / uncommitted" at HEAD `31d30377`. The whole set is now in git:

- `backend/scripts/turn_pipeline_check.py` — **TRACKED**
- `backend/tests/test_turn_pipeline_check.py` — **TRACKED**
- `backend/tests/integration/test_turn_pipeline_check.py` — **TRACKED**
- `backend/scripts/bg_deploy.sh:295` — `IMAGE_TAG="$IMAGE_TAG" docker compose exec -T "web-$color" python -m scripts.turn_pipeline_check` in the post-flip verification
- `backend/scripts/bg_rollback.sh:245` — the mirrored `PREV_TAG` call
- `backend/docker-compose.yml` — healthcheck `start_period` budgets present, including the `180s` budget that covers the 83 s worker preload from the incident

**The two documentation sections also landed, at their new paths.** The docs tree was restructured after this card was opened, so the card's `docs/deployment-guide.md:156-158` and `docs/incident-runbook.md` no longer exist at those locations. The content is present and correct at:

- `docs/ops/deployment-guide.md:159-160` — the turn-pipeline gate step inside post-flip verification
- `docs/ops/incident-runbook.md:117` — the post-flip gate failure path
- `docs/ops/incident-runbook.md:195` — the manual `turn_pipeline_check` invocation for a live host

## What remains, and why this card closes anyway

The card's second half is "cut the next image from that commit so the in-container gate exists before the next flip." That is a **deployment action**, and no deployment was performed or authorized in this sweep. It is not a code defect and not an agent action; it is an operator step.

The card's own Notes are explicit that it "records the landing requirement, it does not authorize an agent to commit unasked." The commit half is done (by the repo owner, not by this sweep). The image cut stays with the operator and belongs to the next `make deploy`, not to this board.

**Operational note worth carrying into that deploy:** the gate now exists in the repo, so the first deploy from a clean checkout will resolve `python -m scripts.turn_pipeline_check` inside the new image rather than failing closed on a missing file. That was the specific hazard the card's Impact section named, and it is closed.

## Problem

The entire remediation for the 2026-09-26 prod bot-silence incident exists only in the working tree at the audited HEAD 31d30377: the new post-flip stall gate, its wiring into both deploy scripts, compose healthcheck budgets, two test files, and the runbook/deploy-guide sections. A fresh clone, CI, or any deploy built from the recorded HEAD silently loses the exact guardrail that would have caught the incident. The remediation report itself flags that the in-container gate needs an image built from 'this commit' — which does not exist until the set is committed.

## Evidence

- backend/scripts/turn_pipeline_check.py:1-36 — new post-flip gate whose docstring cites the 2026-09-26 incident (83 s worker preload); currently untracked
- backend/scripts/bg_deploy.sh:294-298 and backend/scripts/bg_rollback.sh:244-248 — both (tracked) scripts invoke `python -m scripts.turn_pipeline_check` post-flip and abort/roll back on failure
- backend/tests/test_turn_pipeline_check.py:17 and backend/tests/integration/test_turn_pipeline_check.py:29 — both untracked test files import `scripts.turn_pipeline_check`
- docs/deployment-guide.md:156-158 and docs/incident-runbook.md (modified, uncommitted) — ops docs already instruct operators to run the gate
- plans/reports/260926-1325-prod-bot-silence-recovery-completion.md:149-153 — 'the post-flip gate … requires an image built from this commit. Until then the gate would fail-closed on a deploy'

## Impact

Next deploy from a clean checkout ships without the stall gate while the deploy scripts still call it — or a rebuilt image without the file makes every deploy fail closed; CI's 'green for the exact commit' release guarantee is void for the remediation. The incident class the gate closes (bot silent, containers healthy, webhooks 200) becomes undetectable again.

## Suggested fix

Commit the working-tree remediation set as one change: turn_pipeline_check.py, the bg_deploy.sh/bg_rollback.sh hunks, backend/docker-compose.yml healthcheck/start_period budgets, both test files, docs/incident-runbook.md, and the two docs sections; then cut the next image from that commit so the in-container gate exists before the next flip. Committing is the only action — the content is already written.

## Notes

Absorbs the sweep-ledger 'worker-maintenance creation gap in bg_deploy.sh' item — the working tree now fixes it. Owner-owned working tree: this card records the landing requirement, it does not authorize an agent to commit unasked.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
