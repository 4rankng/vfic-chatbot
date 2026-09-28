# BOT-02 — Project-directory advertising (bot02-projects)

**Outcome: complete.** All six deliverables are implemented and every gate is green.
One nuance for integration: a parallel session committed most of this work mid-flight
as `a8b3593e fix(prompt): present the active-project directory instead of echoing the
LG Display example` (context.py, seed, test_persona.py, plus the kanban card). The only
uncommitted delta in the tree is my last edit — the cache-key assertion update in
`tests/test_universal_platform_characterization.py`, made after that commit's snapshot.
I did not commit anything; the tree is left for lead integration.

## What changed, per deliverable

1. **LG example stripped from fixed facts** (`backend/app/graph/context.py`, the
   `_RUNTIME_RETRIEVAL_RULES` company-identity line). The parenthetical
   "(ví dụ LG Display) … làm việc tại nhà máy LG Display, KCN Trảng Duệ, An Dương,
   Hải Phòng" is gone. Kept: the VFIC office facts (MST, Manhattan office address,
   hotline), the PHÂN BIỆT BẮT BUỘC office-vs-plant discriminator (now generic:
   applicants work at the specific project's factory, never at the office), the
   "KHÔNG trả lời VFIC ở KCN Tràng Duệ" guard, and a pointer that active projects
   are enumerated in DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG.

2. **Vague-seeker rule** — added to the directory's instruction block inside
   `active_projects_index` (not the static rules block), so the rule exists exactly
   when the DANH MỤC it points at is rendered. When the candidate is unsure which
   jobs exist or is vaguely looking: present the directory's active projects citing
   only name, location, and card highlights; a project without highlights gets name +
   location plus a consultant-callback ask (xin SĐT); hiring confirmation stays
   anchored to `list_active_jobs`/published KB evidence, never inferred from the
   directory.

3. **Highlights rendered** (`context.py` directory lines). Each line gains
   `; nổi bật: …` sourced only from `index_card["highlights"]` — the key both the
   ingestion card schema (`INDEX_SYSTEM_PROMPT`, app/services/knowledge/prompts.py:44)
   and `ProjectIndexRepo.sync_highlights` write. Empty/missing key renders no segment.

4. **TingTing gate — already exists upstream; verified and pinned, no new plumbing.**
   The account context does not reach context.py (`build_system_prompt` receives only
   the provider label zalo_bot/zalo_oa/facebook_messenger), so a gate inside context.py
   alone is impossible without new plumbing — and none is needed: runner.py:601
   computes `_tingting_reset_allowed` from `channel_identity.account_key` every turn
   and lanes.py:590-609 routes TingTing-OA conversations to
   `tingting_support_system_prompt`, never calling `build_system_prompt`. Existing
   runner-turn tests assert `prompt_calls == []` for the OA. I added
   `test_tingting_support_prompt_excludes_the_recruitment_directory` pinning that the
   support prompt (with and without guide) carries no DANH MỤC header, no vague-seeker
   rule, no `list_active_jobs`.

5. **Seed typo fixed**: `samsung-bac-ning` → `samsung-bac-ninh`
   (`backend/scripts/seed/projects.py:43`). Verified nothing references the old slug:
   seed knowledge links documents positionally (`projects[2].id`), and a repo-wide
   grep (py/ts/tsx/md/json/mjs, excluding node_modules/kanban) found only the
   definition. Seed module imports and `make_projects()` returns the corrected slugs.
   Note: fresh seeds only — an existing prod DB keeps its stored slug; renaming there
   is an admin action, out of scope.

6. **Tests** (in `backend/tests/test_persona.py`, the existing context/prompt home,
   following its `_Repo` stub convention): highlights rendered; highlights segment
   omitted when the card has none/empty; vague-seeker rule present with
   list_active_jobs anchor and strict grounding; fixed-facts block carries no project
   example while keeping office facts + PHÂN BIỆT BẮT BUỘC + DANH MỤC pointer;
   TingTing support-prompt exclusion; and the preamble cache key carries the prompt
   text revision (see below). One existing assertion updated:
   `test_universal_platform_characterization.py` pinned the old cache-key format
   (`key_suffix == "zalo_bot"`); it now pins `f"zalo_bot:r{_PROMPT_TEXT_REVISION}"`.

**Preamble cache correctness.** Code-level rule-text changes are invisible to the
NS_PREAMBLE version bump (only DB card/persona writes bump it), so before this change
a deploy would serve the old rule text from Redis for up to the 10-min TTL. The prior
precedent (75666fb6) accepted that window; the acceptance criterion here forbids it.
Fix: a module constant `_PROMPT_TEXT_REVISION = "2"` folded into the cache-key suffix
(`{provider}:r2`), with the bump convention documented at the constant and in the
`build_system_prompt` docstring. First turn per provider after deploy re-assembles
(one DB-read miss); steady-state hit behavior and per-provider separation are
unchanged; old keys age out via TTL.

## Gate evidence

- `cd backend && .venv/bin/python -m pytest tests/test_graph_runner_turn.py
  tests/test_architecture_boundaries.py tests/test_runtime_surface_inventory.py
  tests/test_persona.py tests/test_persona_resolver_convergence.py
  tests/test_universal_platform_characterization.py tests/test_graph_proactive_turn.py
  -p no:randomly -q`
  → `190 passed in 53.88s`
- The runtime-surface inventory snapshot did **not** need a bump: the AST inventories
  count queue/outbox/provider call names only; this change adds none (verified against
  `CALL_CATEGORIES`/`_BroadCallInventory` and by the passing suite).
- `cd backend && uvx pyright app/graph` → `0 errors, 0 warnings, 0 informations`
- `cd backend && .venv/bin/ruff check app/graph tests/test_persona.py
  tests/test_universal_platform_characterization.py scripts/seed/projects.py`
  → `All checks passed!`

## Open questions / notes for the lead

- **Uncommitted delta**: `backend/tests/test_universal_platform_characterization.py`
  (cache-key assertion) is not in a8b3593e — fold it in during integration, or the
  characterization suite fails on the old key assertion via the error-fallback path.
  (Resolved: integrated in f4540ada with the docs line and card move.)
- **Docs impact (minor)**: `docs/architecture/system-architecture.md:912` lists the
  preamble-index fields as "(name, slug, aliases, discovery summary, roles, and
  location)" — add "highlights". Not edited (outside my ownership).
  (Resolved: f4540ada.)
- The parallel commit also swept in the kanban card file; card state is the lead's to
  manage.

## Extension (lead grant, 2026-09-28 ~22:40): identity-only TingTing prompt gates

The lead's scout map confirmed a real leak and granted two regions: the lanes.py
prompt branch (plus an identity-only helper) and the proactive.py call site. All
shipped, uncommitted, on top of HEAD (8b1225a1).

- **`lanes.py` — `_tingting_account_conversation(conv)`** (new helper next to
  `_tingting_reset_allowed`): provider == zalo_oa AND account_key ==
  TINGTING_OA_ACCOUNT_KEY, no admin pin. `_tingting_reset_allowed` is untouched —
  the reset flow stays pin-gated as the lead directed.
- **`lanes.py` prompt branch**: condition is now
  `tingting_reset_allowed or tingting_support_account`, so a pin-unset TingTing-OA
  turn gets the support persona instead of falling through to the recruitment
  preamble. The project-context append (FOCUSED/EXPLORE blocks, both of which
  reference the project directory) gained the same `not tingting_support_account`
  guard — those blocks must not land on the support prompt either.
- **Plumbing note (one region beyond the literal grant)**: `_agent_turn` does not
  receive `conv`, so the flag is computed in `_resolve_lane` (which has `conv`) and
  forwarded to `_agent_turn` via the existing `_optional_policy_kwargs` filter
  alongside `tingting_reset_allowed`. This adds `tingting_support_account: bool =
  False` to `_agent_turn`'s signature and one dict entry at the forwarding site —
  the smallest possible plumbing for the granted fix shape; runner.py untouched.
- **`proactive.py`**: the context build branches on the same identity check —
  TingTing-OA conversations get `tingting_support_system_prompt` (guide included
  when `deps.retrieval.tingting_api_configured` reads true, guarded like the
  reactive branch); every other conversation keeps `build_system_prompt`.
  Imports `_tingting_account_conversation` from lanes (same direction runner
  already imports `_tingting_reset_allowed`; no cycle).
- **Tests**: `test_support_oa_keeps_the_support_prompt_when_the_reset_link_pin_is_unset`
  (the leak, now pinned shut: pin False + identity True → support prompt,
  `build_system_prompt` unreached) and `test_tingting_support_account_identity_is_pin_free`
  (provider/account matrix, no-identity default) in test_graph_runner_turn.py;
  `test_support_oa_nudge_never_gets_the_recruitment_preamble` in
  test_graph_proactive_turn.py (tingting identity → support persona, marker absent;
  recruitment OA → assembled preamble still used; OA nudge quotes a WORKER inbound
  message per the existing `zalo_oa_requires_inbound_message_id` guard).
- **Adjacent gap (lead-ordered fix, shipped)**: `_resolve_lane`'s two curated
  lane-selection gates (project_clarification / direct-context) keyed on
  `not tingting_reset_allowed` only, so a pin-unset TingTing-OA conversation with a
  resolved clarification/direct-context could still take a recruitment-data lane
  before the prompt branch. Both conditions now also require
  `not tingting_support_account`; the flag is computed once at the top of
  `_resolve_lane` and reused by the forwarding dict. Coverage:
  `test_support_oa_never_takes_the_curated_recruitment_lanes` drives both paths on
  a pin-unset TingTing identity (lane falls through to agent, flag forwarded,
  direct-context turn never invoked) with recruitment-OA controls proving each
  lane still selects for non-support accounts.
- **Tooling note**: `git status`/`git log` output in this session was repeatedly
  mangled by the repowise distill wrapper (empty or missing lines, including a
  false "my edits vanished" reading); raw `command git` shows the tree correctly.

### Extension gate evidence

- `pytest tests/test_graph_runner_turn.py tests/test_architecture_boundaries.py
  tests/test_runtime_surface_inventory.py tests/test_graph_proactive_turn.py
  tests/test_persona.py tests/test_persona_resolver_convergence.py
  tests/test_universal_platform_characterization.py tests/test_tingting_api.py
  -p no:randomly -q` → `244 passed in 64.22s` (243 before the gap fix; the new
  lane-selection test is the delta)
- `uvx pyright app/graph` → `0 errors, 0 warnings, 0 informations`
- `.venv/bin/ruff check app/graph tests/test_graph_runner_turn.py
  tests/test_graph_proactive_turn.py` → `All checks passed!`

Docs impact: minor — one field name ("highlights") missing from the preamble-index
enumeration in docs/architecture/system-architecture.md:912 (resolved in f4540ada);
everything else is code-internal behavior already covered by the architecture doc's
existing invariant that hiring authority stays with list_active_jobs.
