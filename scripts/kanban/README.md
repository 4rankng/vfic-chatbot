# Tech-debt board — generator & notes

The board itself lives in `kanban/` and follows the house kanban convention:
exactly four column folders, one card per file, no index and no sidecars inside
the board.

```
kanban/
  TODO/            waiting
  IN_PROGRESS/     claimed, being implemented
  DEV_COMPLETED/   local criteria evidenced
  QA_TESTED/       verified locally end to end
```

Cards are markdown named `YYYYMMDD_<ID>-<slug>.md` — date prefix, stable ticket
id, kebab-case slug. The id stays in the filename because the cards
cross-reference each other by id (e.g. "see REL-05").

Deviation from the `kanban-work` practice: cards are `.md`, not `.docx`. These
are developer-facing cards whose whole value is `path:line` evidence in a
git-tracked repo, so markdown keeps them diffable and reviewable. The column
structure, one-task-one-file rule, and "the folder must match the card's true
state" rule are followed as-is.

## Regenerating

`tickets_*.py` in this directory are the source of truth for card content **and**
column:

```bash
python3 scripts/kanban/build.py
```

The build clears each column first, so a rename or a column change cannot leave
a stale duplicate. To move a card, set its `column=` in the data module and
rebuild — do not hand-move files, and do not hand-edit a generated card.

## Origin

### Wave 2 — 2026-09-26 (HEAD `31d30377`)

49 cards (`ARCH-20`…`ARCH-28`, `DOC-14`…`DOC-18`, `FE-20`…`FE-26`, `OPS-21`…`OPS-27`,
`PERF-15`…`PERF-17`, `REL-8`…`REL-15`, `SEC-9`…`SEC-11`, `TEST-16`…`TEST-22`), all
starting in `TODO/`. They came from a nine-lane parallel read-only audit (backend
architecture, backend correctness, backend performance/async, security, graph/bot,
frontend, testing/CI, ops/deploy/dependencies, docs/repo hygiene) run against the
tree left by the swept wave-1 board. Data module: `tickets_e.py`. Ids continue each
area sequence from wave 1. Known/deferred items (SEC-01, K-4/K-10/K-11/K-12, the
sweep-ledger holds, the FE-02/FE-08 QA-blocked edges) were excluded from carding;
audit-time baseline: ruff clean, backend unit `2397 passed / 24 skipped`, frontend
tsc + eslint clean. `TEST-22` was retired on 2026-09-27 with the OpenWiki teardown:
its subject workflow (`.github/workflows/openwiki-update.yml`) no longer exists, so
the card and its `tickets_e.py` entry were removed together.

### Wave 1 — 2026-09-24 (HEAD `923b1d3f`)

Every wave-1 card came from the read-only tech-debt audit of **2026-09-24** (HEAD
`923b1d3f`, `main`), which ran eight parallel read-only scouts over disjoint
slices: backend architecture, backend correctness, backend performance,
security, frontend, testing/CI, dependencies/ops/migrations, and repo hygiene.
Every claim in every card is anchored to a `path:line` in the tree at that
commit.

Audit-time baseline: backend unit suite `2243 passed, 42 skipped, 88 deselected`
in 23.4 s; `ruff check .` clean; `tsc --noEmit` clean. The tree was lint-clean
and type-clean, so the debt is structural, not stylistic.

## Not tickets

Findings the audit deliberately records as *not* defects, so they are not
re-litigated:

- The layering rules (`API → Services → Models/Core`, `graph/` behind
  `graph/ports.py`) are machine-enforced with a zero-entry allowlist and are not
  violated.
- The pre-send ownership claim (`claim_send`) is genuinely atomic; the outbox
  claim cannot double-send.
- Raw SQL is static or whitelist-built; no SQL injection, XXE, path traversal,
  or SSRF was found.
- No hardcoded secrets; `backend/.env` is untracked and ignored;
  credential-bearing transport loggers are silenced.
- Socket.IO enforces per-room authorization on connect and on every join.
- `assets/showoff`, `openwiki/`, and `kb/` are tracked but are classified as
  artifacts by other ignore files — the fix is a `.gitignore` rule, not a
  rewrite.

## Deferred by request

Confirmed findings deliberately **not** carded yet. Recorded so they are not
lost or re-discovered from scratch.

**Unauthenticated Zalo OA webhook.** `POST /webhooks/zalo/oa`
(`backend/app/api/webhooks.py:148-188`) performs no authentication of any kind —
signature verification was deliberately disabled because the stored credential is
the wrong Zalo secret (`backend/app/api/webhooks.py:171-176`). Any unauthenticated
caller can create conversations, create and update leads, and enqueue real LLM
turns: dedup is per `(sender, msg_id)`, so looping fresh sender ids yields
unbounded cost against `llm_concurrency_limit = 8` on a 2 vCPU box. It is the only
credential-free state-changing endpoint in the application.

Root cause: the app holds the OA *access-token* secret rather than Zalo's webhook
checksum key, so the (correct) verifier at
`backend/app/services/zalo_oa_signature.py:verify_signature` could never pass.
Fixing the code without fixing the credential would false-reject 100% of real
events. Either obtain the checksum key and wire the verifier into the inbound
route, or delete the route if the OA channel is not in production use.

## Withdrawn ticket ids

Ids are allocated once and never renumbered, so the security sequence starts at
`SEC-02`. **SEC-01 was withdrawn by request before the board was published** and
is deliberately not a card — it is the unauthenticated Zalo OA webhook recorded
above. The tuple lives in `tickets_a.py` under `WITHDRAWN`; the gap is
intentional, and no card is missing.
