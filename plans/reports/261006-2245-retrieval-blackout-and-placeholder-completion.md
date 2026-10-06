# Completion — retrieval blackout root cause, orphan placeholders, tuning review

## Task record

- Task: (1) Fix the LG thưởng retrieval blackout end to end — root cause, prod
  remediation, regression pin. (2) Fix the orphaned "Đang soạn trả lời..."
  FAILED placeholder rows. (3) Review FAQ / chat workflow / agent persona for
  answer-quality tuning against the 2026-10-06 candidate interaction history.
- Scope: `app/graph/embed_cache.py`, `app/graph/embedders.py` (cache-namespace
  fix, `0de441e0`), `app/graph/progressive.py` (placeholder-orphan fix,
  `36da77f4`), prod Redis remediation, tuning review. Extraction-reliability
  and lead-ask work by the parallel session committed separately (`1ecc30e4`,
  `fd95b342`).
- Files changed (this session's own commits):
  - `backend/app/graph/embedders.py` — `build_embedder` stamps the resolved
    provider/model on each client.
  - `backend/app/graph/embed_cache.py` — `cached_embed` keys on that stamp,
    env only as fallback.
  - `backend/tests/test_graph_tools.py` — cache-key regression pin.
  - `backend/tests/test_embedder_openrouter_always_on.py` — stamping pin.
  - `backend/app/graph/progressive.py` — ground the remainder BEFORE creating
    its placeholder; empty-after-grounding takes the whole-answer terminal.
  - `backend/tests/test_graph_runner_turn.py` — two progressive pins.
- Instructions retrieved: root `AGENTS.md`, `docs/ops/deployment-guide.md`,
  `standards/agent-completion-checklist.md`.
- Approval required: user-directed ("fix them all, commit, push and deploy",
  release-check explicitly waived).
- Approval evidence: user instruction in session.

## Root cause (retrieval blackout) and remediation

- `cached_embed` built its Redis key from **env** embedding settings while the
  embedder is built from the **Settings-page** resolution. With the page briefly
  set to gemini (env still `openrouter`), Gemini vectors were stored under
  `embed:openrouter:*` keys and served for the 24h embed TTL: cosine ≈ 0.00
  against every chunk, every retrieval empty, and the bot truthfully answered
  "chưa có thông tin đã xác minh" (grounding held; infrastructure lied to it).
- Measured proof: cached-vs-fresh cosine 0.0071 / −0.0033 on the two incident
  queries; stored chunk embeddings are OpenRouter-space (0.6374 vs fresh).
- Remediation: purged all `embed:openrouter:*` keys on prod (65 keys, verified 0
  remain); the stamp fix makes any future provider flip land in a fresh,
  empty namespace instead of poisoning the live one.

## Orphan placeholder fix

- `_complete_progressive_prefix` created the remainder's PENDING placeholder
  before grounding; a grounding-suppressed remainder exited without resolving
  it — 42 FAILED "Đang soạn trả lời..." rows since 2026-07-14, three in the
  incident conversation. Grounding now precedes `record_bot_pending`; the
  empty-after-grounding case takes the whole-answer-was-the-bubble terminal.

## Tuning review (FAQ / workflow / persona) — evidence-based outcome

- **Persona**: no change. The incident conversation shows slang handling, no
  hallucination, correct escalation offer, phone/shift/start-week capture all
  working. The miss was infrastructure, not persona.
- **Floors**: no change. Measured: floor 0.25 does not rescue the exact slang
  phrasing (its best visible-thưởng similarity is below it) while admitting
  more noise; 0.30 stays.
- **FAQ variants (content action, needs sheet/console access)**: add to the
  thưởng FAQ entries (LG-DISPLAY Google Sheet row; LG Electronics faq.md via
  the console category editor):
  `question_variants: ["thời vụ có thưởng không", "làm thời vụ có được thưởng không", "thời vụ có dc thưởng k", "time vụ có thưởng hông", "vào làm tháng 10 có thưởng không"]`
  Variants feed the chunk embedding at ingest (`pipeline.py` embeds
  content+summary+questions), which is the only reliable lift for slang
  phrasings.
- **Raw docx on LG Electronics** (`BIEU_MAU…LGE.docx`, `LGE.docx`): invisible by
  design — source archives; the governed category md files carry the same
  content and are visible. No action.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior complete | PASS | Cache namespace fix + prod purge + progressive fix; retrieval verified live post-purge |
| Diff limited to approved scope | PASS | 6 files across two scoped commits; parallel-session work committed separately |
| Protected operations avoided/approved | PASS | User-directed deploy; release-check waived by user; no migration touched |
| Focused tests pass | PASS | `test_graph_tools.py` + `test_embedder_openrouter_always_on.py` (79), `test_graph_runner_turn.py` (179) |
| Broader regression pass | PASS | retrieval scope guards, failover, parallel tools, answer-cache turn (61); composition + outbox (33) |
| Lint passes | PASS | `ruff check` on all four backend files: clean |
| Type checking | N/A | Backend gate is pyright-scoped to `app/graph` in release-check (waived by user); files are typed, tests green |
| Build/import validation | PASS | Full pytest import surface exercised |
| Security/privacy | PASS | No new IO surface; Redis cache content unchanged in kind; no PII in logs |
| Performance/async | PASS | Same call count; key derivation is CPU-only string work |
| Accessibility/Vietnamese UX | PASS | No user-visible copy change except removal of dead FAILED bubbles |
| Error handling/compatibility | PASS | Env fallback preserves unstamped-embedder behavior (pinned by test) |
| Documentation impact | PASS | This report; code comments carry the durable rationale at both fix sites |
| No new TODO/FIXME/HACK | PASS | None |
| `git diff --check` | PASS | Clean |
| `git status --short` | PASS | Clean at commit time |

## Result

- Overall status: DONE (deploy follows this commit; release-check waived by user)
- Remaining risks or follow-ups:
  - FAQ variant rows must be applied by a human with Sheet/console access
    (exact text above); until then, very slangy thưởng phrasings may still miss.
  - The 42 historical FAILED placeholder rows remain in the DB (cosmetic CRM
    noise); a one-off cleanup could archive them if recruiters complain.
  - Deploy tonight recreated workers repeatedly; watch `/health/queue` for
    backlog after cutover.
