---
id: BOT-01
title: "Chatbot escalates to consultant on the first out-of-scope/small-talk reply instead of redirecting to reveal intent"
severity: medium
area: bot
labels: [bot-behavior, escalation, tingting-support, conversation-flow]
effort: M
status: qa_tested
column: QA_TESTED
opened: 2026-09-28
---

# BOT-01 — Chatbot escalates to consultant on the first out-of-scope/small-talk reply instead of redirecting to reveal intent

**Severity:** medium · **Area:** bot · **Labels:** bot-behavior, escalation, tingting-support, conversation-flow

**Trạng thái:** QA_TESTED — fix implemented 2026-09-28 (owner blanket-approved), unit + turn suites green (168 passed). **NOT YET DEPLOYED** — needs a backend image build + `make deploy` to reach prod.

## Problem

On the TingTing support flow the bot escalates to a human consultant after a single
small-talk reply, without ever asking the user what they actually need. Reproduced
THREE times in production on 2026-09-28:

| Time | Channel | Transcript |
| --- | --- | --- |
| 08:39–08:40 | TingTing support OA (console) | `hi` → confirm question → `hôm nay trời đẹp đấy` → `Vui lòng chờ chuyên viên tư vấn liên hệ.` |
| 14:35 / 14:50 | TingTing OA (Zalo app) | confirm question → `trời đẹp lắm` → handoff; user returns 15 min later (`hello` → confirm → `trời đẹp`) → handoff again |
| 14:57–14:59 | "Công ty Việt Pháp" OA | `địa chỉ VFIC ở đâu` → handoff (separate root cause: KB had no VFIC office data — fixed separately, see `backend/scripts/patch_vfic_office_kb.py`) |

Console separator under the first incident: `Luồng trích xuất đề nghị nhân viên xác minh ý định liên hệ.`

## Root cause (verified in code)

`backend/app/graph/tingting_guide.py` ordered an instant handoff:

- persona rule: «MỌI việc khác (…hoặc **bất kỳ chủ đề nào khác**): trả lời ĐÚNG NGUYÊN VĂN …
  «Vui lòng chờ chuyên viên tư vấn liên hệ.»» — small talk matched "any other topic";
- API-guide rule: «Nếu câu trả lời không phải là việc đặt lại mật khẩu thì trả lời đúng dòng
  «Vui lòng chờ chuyên viên tư vấn liên hệ.» **và không làm gì thêm.**» — any non-password-reset
  reply escalated on the spot, no retry budget existed.

## Fix (implemented 2026-09-28)

`backend/app/graph/tingting_guide.py`:

1. New fixed reply `TINGTING_INTENT_REDIRECT_REPLY` — the verbatim re-ask for
   no-clear-need replies. Deliberately does NOT contain the handoff line, because
   `lanes.py` detects handoff replies by that exact sentence to write `needs_human`;
   a redirect containing it would escalate on the first small-talk turn.
2. Persona PHẠM VI + API-guide "Trạng thái hội thoại" now:
   - classify small talk (weather, greetings, "ok", "rồi") as unclear intent —
     explicitly NOT a "chủ đề khác";
   - redirect with the fixed re-ask, budget **tối đa 3 LẦN** asks per conversation
     (counted from history), handoff only after the 3rd no-progress answer;
   - keep the immediate handoff for **explicit** out-of-scope requests, verification
     exhaustion, and the no-API-config path (unchanged).

Regression test: `backend/tests/test_tingting_api.py::test_small_talk_gets_a_redirect_budget_before_any_handoff`
asserts the classification, the 3-ask budget, the verbatim redirect quote in both
prompt sections, and that the handoff line never appears in the redirect wording.

Verification: `uv run pytest tests/test_tingting_api.py tests/test_graph_runner_turn.py`
→ **168 passed** (includes the runner persona-contract test).

## Rollout checklist

- [ ] Commit + push the tingting_guide change (with the VFIC KB converter mapping + patch script from the same day).
- [ ] `cd backend && make push && make deploy` (blue/green + smoke gate).
- [ ] Prod QA: `hi` → confirm → `trời đẹp` → expect the redirect ask, NOT the handoff line; third no-progress answer → handoff line.

## Notes

- Owner directive 2026-09-28: "bot should at least try few times" — implemented as a
  3-ask budget; adjust the number by editing «tối đa 3 LẦN» in both prompt sections.
- The 14:57 handoff on the "Công ty Việt Pháp" OA for `địa chỉ VFIC ở đâu` had a second
  root cause — the KB contained no VFIC office address (and the old answer conflated the
  LG Display factory address with the company). Fixed in prod KB on 2026-09-28:
  contacts rev 3 + faq rev 7 activated with the real office data
  (Manhattan 07-08, Vinhomes Imperia, Hồng Bàng, Hải Phòng; hotline 1800 7228; MST 0201307104),
  `contact_info` feature JSON updated as source of truth, converter mapping patched in
  `legacy_category_backfill.py` so future backfills keep it.

---

_Opened 2026-09-28 from the owner's production reports (three incidents). Fix verified by test on 2026-09-28; deployment pending._
