# Agent Completion Report — Candidate source attribution (first touch)

## Task record

- Task: Give the app the information a candidate's message came *from* — the
  post / ad behind the entry — on both Messenger and Zalo OA, under the stated
  assumption that Zalo provides the prefill link
  `https://zalo.me/<oa>?text=<MÃ_BÀI_VIẾT>`.
- Scope: backend capture + persistence + read-only API exposure for the two
  encodings that exist today. Explicitly out of scope: recruiter-UI display of
  the source, Zalo Ads *form* lead polling (`oa/form/get`, a separate path),
  and later-touch (re-entry) attribution — the record is first-touch by design.
- Files changed (mine, 21): migration `0069_conversation_attribution`;
  `models/conversation.py`, `schemas/conversation.py`;
  `services/conversation/{_shared,bot_path,service,state}.py`;
  `services/webhook.py`; `channels/{ingress,types}.py`;
  `channels/providers/{facebook_messenger,facebook_oauth}.py`;
  `conversation_messaging/application/ingress.py`;
  `conversation_messaging/infrastructure/{ingress,webhook_delivery}.py`;
  `api/webhooks.py`; `tests/test_candidate_attribution.py` (new);
  `tests/integration/test_candidate_attribution.py` (new);
  `docs/architecture/system-architecture.md`, `docs/ops/deployment-guide.md`,
  `docs/product/codebase-summary.md`. 18 tracked files +300/−5, 3 untracked.
  The worktree also carries an **unrelated in-flight session** (`app/graph/*`,
  `tests/test_graph_*`, `tests/test_tingting_api.py`,
  `tests/test_runtime_surface_inventory.py`) — deliberately not staged by me.
- Instructions retrieved: `AGENTS.md`; `docs/development/code-standards.md`;
  `docs/development/testing.md`; `docs/architecture/system-architecture.md`;
  `docs/ops/deployment-guide.md`; `standards/agent-completion-checklist.md`.
  Provider contracts verified against primary docs: Meta `messages` /
  `messaging_referrals` / `messaging_postbacks` webhook references; Zalo OA
  `user_send_text` and `user_click_chatnow` events plus the full OA doc corpus.
- Approval required: none yet for this task (no commit/push/deploy requested).
- Approval evidence: N/A — code verified locally, awaiting the user's call.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Zalo: a leading `#CODE` in the first message is recorded (`services/webhook.py::_post_link_attribution`, Bot + OA). Messenger: `message.referral` (ad id + ads post id) rides the message; Get Started/m.me `postback.referral` is stamped conversation-only (`api/webhooks.py` → `webhook_delivery.apply_messenger_referral`). First touch persists in `conversations.attribution` and is exposed as `attribution` on `ConversationOut`. Proven against real PostgreSQL (3 integration tests below). |
| Diff is limited to the approved scope | PASS | `git diff --stat -- <my 21 paths>` → 18 tracked files, +300/−5 (+3 new). Foreign in-flight edits listed above were left untouched. |
| Protected operations were avoided or approved | PASS | No commit, push, branch, PR, or deploy performed (none requested). Migration is additive nullable JSONB; only the local dev DB was upgraded (`alembic upgrade head` → `0068 → 0069`). |
| Focused tests/checks pass | PASS | `pytest tests/test_candidate_attribution.py -q` → **13 passed** (Zalo code rule incl. digit/no-digit/leading-position cases, Messenger referral mapping, postback extraction with cross-Page exclusion, subscription field list, merge rule). `pytest tests/integration/test_candidate_attribution.py -m integration -q` → **3 passed** (persist on the inbound transaction, first touch survives later touches, referral stamp commits alone, API projection, NULL stays NULL). |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -q -m "not integration"` → **3678 passed, 28 skipped, 1 failed** (16m25s). The single failure is `test_direct_turns.py::test_typing_bridge_never_falls_back_to_stale_environment_token`, a pre-existing load-flaky timing assertion (expects ≥3 resolves inside a 65 ms window): `pytest tests/test_direct_turns.py -q` → **14 passed in 1.00 s** on the same tree. It flaked the same way on the previous release run under load and touches nothing in this change. |
| Lint passes for affected code | PASS | `backend/.venv/bin/ruff check .` → "All checks passed!" |
| Type checking passes for affected code | PASS | `uvx pyright app/graph` → "0 errors, 0 warnings, 0 informations" (the release gate's type scope; my edits sit in `app/services`, `app/channels`, `app/schemas`, `app/conversation_messaging`). |
| Build/import validation passes for affected code | PASS | Dev DB migrated (`Running upgrade 0068 → 0069`); the integration tests exercise the real stack end-to-end (ensure → record_inbound → JSONB column → pydantic projection). |
| Security and privacy impact reviewed | PASS | The record holds only provider ids and our own campaign codes (`ad_id`, `post_id`, `ref`, `#CODE`) — no message text, no PII, no tokens; log lines carry the account suffix only. Referral events are scoped to the connected Page (`referrals_from_payload(page_id=…)`), so another Page's events can never write into this deployment. The raw webhook payload is still never persisted. |
| Performance and async-I/O impact reviewed | PASS | One JSONB column write folded into the transaction that already commits the inbound — no extra query, round trip, task, or loop. The referral-only stamp costs one idempotent ensure + one commit on a rare event; `merge_attribution` is in-memory. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. Recruiter-facing display of the source is a stated follow-up. |
| Error handling and compatibility reviewed | PASS | `attribution` is optional at every layer (old rows, old clients, and callers that pass nothing behave exactly as before: NULL stays NULL). `stamp_attribution` swallows and rolls back — a source hint can never fail a webhook ack; the postback loop is wrapped like the receipts loop. A redelivery returns before the stamp (no double write). Migration is additive ⇒ blue/green safe. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `system-architecture.md` §2.4 (encodings, code rule, first-touch rule, Zalo platform limitation, Page re-subscribe requirement); `deployment-guide.md` §4 HEAD → `0069_conversation_attribution`; `codebase-summary.md` module row. `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets … resolve". |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff -- <my paths> \| grep -E '^\+.*(TODO\|FIXME\|HACK)'` → no matches. |
| Final `git diff --check` passes | PASS | `git diff --check -- <my paths>` → exit 0. |
| Final `git status --short` reviewed | PASS | 29 paths: my 18 modified + 3 new, plus the unrelated in-flight session's 8 files (listed in the task record) — reviewed, deliberately left unstaged. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - **Page re-subscribe:** Meta delivers a Click-to-Messenger ad's referral only
    when the Page is subscribed to `messaging_referrals` *and* `messages`.
    `subscribe_app_to_page` now asks for it, but a Page connected before this
    change keeps the old list until it is disconnected/reconnected — otherwise
    `message.referral` (and with it `ad_id`/`post_id`) is silently absent.
  - **Zalo platform limit:** the OA webhook carries no ad/post id at all
    (corpus-verified 2026-10-06), so per-ad Zalo attribution can only come from
    Zalo Ads form leads via `GET openapi.zalo.me/v2.0/oa/form/get` (`adId`) —
    a separate polling integration, not implemented here.
  - **Codes must contain a digit** (`#BV1026` yes, `#tuyen` no) — the rule that
    keeps candidate prose from becoming a source; marketing must follow it when
    building links (`%23` + code).
  - **Postback stamping creates the conversation early** (a Get Started with a
    referral yields a thread with no messages until the candidate types). Chosen
    deliberately: the alternative is losing `ref` for every new m.me entrant.
  - No recruiter UI for the source yet; it is on `ConversationOut` and queryable
    (`attribution->>'ad_id'`).
  - Pre-existing: `test_direct_turns.py::test_typing_bridge_…` is timing-based
    and flakes under CPU load (passes alone); worth making clock-driven like
    `tests/test_chat_status.py`.
