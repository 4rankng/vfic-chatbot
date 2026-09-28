# BOT-03 — TingTing post-resolution closer (kanban BOT-03)

## Outcome

All four deliverables are implemented, the mid-task duplicate-rule conflict is
reconciled per the lead's ruling, and every acceptance gate is green on the
reconciled file. One follow-up for the lead: a parallel session committed its own
BOT-03 version (`8b1225a1`) and moved the kanban card to DEV_COMPLETED
(`78b7a474`) before the reconciliation landed — the reconciled rules exist only
as unstaged worktree changes and need a commit by whoever is allowed to commit.

## Per-deliverable changes

### 1. Fixed closer reply

`backend/app/graph/tingting_guide.py:67` —
`TINGTING_RESOLVED_CLOSER_REPLY = "Dạ không có gì ạ, em luôn đây khi anh/chị cần hỗ trợ 😊"`,
verbatim as owner-approved, with the file's fixed-reply comment conventions
(operator-approved words, quoted verbatim; must never contain
`TINGTING_CONSULTANT_HANDOFF_LINE` because the lanes escalation hook keys on that
line). Added to `__all__`.

### 2. Post-resolution rules (reconciled set)

Persona (`backend/app/graph/tingting_guide.py`, after the redirect-budget bullet):

- `HỘI THOẠI ĐÃ GIẢI QUYẾT XONG` — closers/thanks/gibberish get the closer
  verbatim, no re-pitch; renewed login trouble is a new need and goes straight to
  the three-field ask with no re-confirmation (lead ruling #2).
- `Câu xác nhận ... đã được hỏi MỘT LẦN` — after one clarifying ask, a
  thanks/OK-closer or gibberish answer gets the closer and the question is not
  asked a second time. This is the single place the once-cap lives (lead ruling
  #3); `TỐI ĐA MỘT LẦN` now appears zero times in the file.

API guide, `Trạng thái hội thoại`: mirrored pair — closer on resolved social
turns with straight-to-fields re-engagement, plus the same once-asked rule.

Supporting scoping edits (both sections): `"ok", "rồi"` removed from the
social-bullet example lists so those messages are governed by the closer rule
instead of the redirect — that overlap was the incident's firing path. The
3-ask redirect budget and the lanes escalation backstop are untouched.

### 3. Deterministic-path grep — clean, no STOP

`TINGTING_CONFIRM_REPLY` and `TINGTING_INTENT_REDIRECT_REPLY` are emitted only
from `tingting_guide.py` itself. Outside the guide they appear only as comments
(`router.py:187`, `lanes.py:448`). Deterministic support-OA emissions in
`lanes.py` are a different reply pair: `TINGTING_RESET_REDIRECT_REPLY`
(`lanes.py:442`, channel-not-allowed) and handoff replies (`lanes.py:463-464`);
the clarify path only forces the route intent (`lanes.py:453-459`), the model
still speaks the prompt's fixed lines. No guard outside the guide is needed.

### 4. Tests

`backend/tests/test_tingting_api.py` — import of
`TINGTING_RESOLVED_CLOSER_REPLY` plus two tests following the file's
prompt-content conventions:

- `test_resolved_conversation_gets_the_closer_not_another_pitch` — closer quoted
  verbatim in both prompt sections, resolved-state rule present, once-asked rule
  (`KHÔNG hỏi lại lần thứ hai`) present, re-engagement condition present, handoff
  line absent from the closer.
- `test_login_trouble_after_resolution_re_engages_the_reset_flow` — re-engagement
  condition sits alongside the untouched login-trouble entry (`RẮC RỐI ĐĂNG
  NHẬP` → straight to the three-field ask).

No existing test asserted the old unclear-intent behavior for closers, so none
needed updating; `test_small_talk_gets_a_redirect_budget_before_any_handoff`
still passes unchanged.

## Reconciliation (lead ruling: merge both rule sets)

A parallel session had added overlapping post-resolution bullets to this file
mid-task and then committed them (`8b1225a1`). Per the lead's ruling I merged
both into one set: the foreign bullets' straight-to-fields re-engagement
semantics won (dropping my conflicting re-confirmation cap), the once-cap is
stated once per prompt section, the foreign overlong lines and the dangling
`Đếm trong lịch sử...` continuation were fixed, and the `"dạ"`/`"ô kê"` closer
examples from the foreign wording were kept. One wrinkle worth recording: the
first reconciled draft wrapped `rắc rối` and `ĐÃ GIẢI QUYẾT XONG` across source
lines, which broke the tests' substring assertions — the wrap points were moved
so every asserted fragment stays on one source line.

## Gate evidence (reconciled file)

- `tests/test_tingting_api.py tests/test_tingting_verify_exhaustion.py
  tests/test_persona.py -p no:randomly` → `74 passed in 5.34s`.
- `tests/test_graph_runner_turn.py tests/test_runtime_surface_inventory.py
  tests/test_architecture_boundaries.py -p no:randomly` → `146 passed in 51.84s`;
  no inventory snapshot bump needed.
- `uvx pyright app/graph` → `0 errors, 0 warnings, 0 informations`.
- `.venv/bin/ruff check app/graph` → `All checks passed!`

## Open questions

1. The reconciled rules are unstaged worktree changes on top of `8b1225a1`
   (which already carries the parallel session's duplicate-rule version), and
   `78b7a474` already marked the card DEV_COMPLETED — the lead should commit the
   worktree reconciliation so HEAD matches the ruled semantics.
2. The worktree also carries other teammates' in-flight changes (`lanes.py`,
   `proactive.py`, `test_graph_proactive_turn.py`,
   `test_graph_runner_turn.py`) — untouched by me; flagging so the commit, if
   scoped by path, includes only `tingting_guide.py` and
   `test_tingting_api.py`.

Docs impact: none — the change adjusts prompt rule text inside one code module
and its tests; no user-facing command, setup, contract, or architecture surface
changed.
