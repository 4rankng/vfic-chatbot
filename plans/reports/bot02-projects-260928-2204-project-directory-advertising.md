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
- **Docs impact (minor)**: `docs/architecture/system-architecture.md:912` lists the
  preamble-index fields as "(name, slug, aliases, discovery summary, roles, and
  location)" — add "highlights". Not edited (outside my ownership).
- The parallel commit also swept in the kanban card file; card state is the lead's to
  manage.

Docs impact: minor — one field name ("highlights") missing from the preamble-index
enumeration in docs/architecture/system-architecture.md:912; everything else is
code-internal behavior already covered by the architecture doc's existing invariant
that hiring authority stays with list_active_jobs.
