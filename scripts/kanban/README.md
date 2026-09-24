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

Every card came from the read-only tech-debt audit of **2026-09-24** (HEAD
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
(`backend/app/api/webhooks.py:107-165`) performs no authentication of any kind —
signature verification was deliberately disabled because the stored credential is
the wrong Zalo secret (`backend/app/api/webhooks.py:138-146`). Any unauthenticated
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
