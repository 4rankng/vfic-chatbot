# Investigation: bot claimed "no project at VSIP" (02/10/2026)

## Outcome

The bot asserted a global negative on a turn whose only evidence was a scoped KB
search and a bus-timetable lookup. The catalog tool — the matching authority for
"does any project work at X" — was never called, and nothing in the pipeline
re-checked the claim. The fix converts exactly that shape into a verified or
hedged answer: commits `4752837c` and `5d6f8154` (02 Oct, branch `main`).

## What happened (prod, conversation 60badcf3, times UTC)

- 11:10:14 candidate: "gần núi đèo là vsip chứ", mid-flow after two LG Display
  turns. Run 3371 started only at 11:12:58 with `execution_source: "recovery"`
  (2m44s late — separate latency incident, still open).
- The turn was EXPLORE, `intent=recommend` at route confidence 0.27. The
  catalog is forced only on `vacancy_listing`; this message read as neither, so
  the model picked its own tools: `search_knowledge` + `search_bus_timetable`.
  The KB search missed AMTRAN's VSIP chunks; the timetable search returned LG
  Display's Núi Đèo route; and the model concluded "no project at VSIP".
- 11:23:12 candidate: "vo ly, kiem tra laij KB xem". Run 3375 took the same
  route family but also called `list_active_projects`; the unscoped KB search
  then found AMTRAN's 64 VSIP-bearing chunks and the answer corrected itself.

## Evidence trail

- `alembic_version` = 0059, so the 19:13 turn's decision trace still existed
  and recorded the per-model-turn tool names for both runs.
- `stage_timings` for both runs showed `project_context_state: "EXPLORE"` —
  focus pinning did not apply, disproving the leading code-level hypothesis.
- AMTRAN's categories were all ACTIVE since 05:21 UTC; the audit log shows no
  data change between the turns. The selftest-floor (db539a37) and the three
  KB-resilience fixes were already in prod's image (`6926f87e`, deployed 18:06
  +07 — the same build the incident ran on).
- The card could never have matched anyway: AMTRAN's `index_card.location` is
  "Hải Phòng" (ProjectCreate shortens the workplace address to the city before
  buildJobsMarkdown — a documented gap in `services/geo/project_address.py`),
  and "VSIP" appears in no aliases or card field. Only chunk content carries
  the industrial park; 64 chunks mention VSIP.

## Fix delivered

`backend/app/graph/absence_guard.py` detects replies asserting a project-unit
absence ("chưa có dự án / nhà máy / công ty / khu công nghiệp ...") when the
turn surfaced no catalog evidence. `_absence_self_check` in `lanes.py` then
re-runs the agent once with `list_active_projects` required and unscoped
`search_knowledge` allowed, focus lifted for that single call. A check that
still finds nothing ships the model-authored hedge opening with "Theo dữ liệu
hiện tại ..." plus the admin-editable hotline; an empty generation suppresses
the turn rather than shipping the false claim. Progressive early bubbles
matching the pattern defer to the whole-reply path. `stage_timings` now also
carries `route_reason`, `tool_call_counts`, `prefetch_tool_names`, and
`tools_invoked`, so the next incident of this family is diagnosable from the
DB alone. Kill-switch: `ABSENCE_GUARD_ENABLED` env var.

The unscoped-search fallback is load-bearing until the card-location gap
closes: the catalog still cannot match "VSIP" today.

## Deferred (coordinated, not dropped)

Card-location matching (Fix B): a parallel session owns `recommendation.py`,
`category_projections.py`, `catalog_repository.py`, `tools/catalog.py`,
`services/project/service.py`, and `config.py` in flight — a geo-distance
feature (migration 0061, `services/geo/`, `extracted_address` + coordinates)
whose grounded verbatim address is exactly the value Fix B needs surfaced into
the card. Extending that work to token matching (rank_projects company filter +
card location) lands after theirs, avoiding parallel edits to the same files.

## Verification

- 26 detector unit tests, 11 lane-level tests (19:13 repro: one self-check,
  then verified or hedged+hotline; evidenced/timetable/support/feature-absence
  turns never retry; empty retry suppresses; kill-switch honored).
- Adjacent invariants green: test_llm_authors_every_reply (24),
  test_agent_loop_guards + test_answer_completion_guard (24), and
  test_graph_runner_turn (170).
- ruff check clean on all touched files.
- Full non-integration backend suite: 3585 passed, 10 failed — all 10 belong to
  the parallel geo session's uncommitted working tree (its `tools/catalog.py`
  concrete `services.geo.geocoding` import trips `test_graph_import_guard`, and
  its `row.latitude` reads race its own not-yet-updated
  `test_project_catalog_features` fixtures). None of the failures involve the
  guard's files or commits; this session's committed code introduces zero
  failures.

## Ops notes for the owner

- The guard takes effect on the next deploy; prod still runs `6926f87e`.
  Operator runs `make release-check` first, then `make deploy` (ungated per the
  30 Sep ruling); commit nothing while it runs.
- Run 3371's 2m44s recovery-path start deserves its own investigation.
