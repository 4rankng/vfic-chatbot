---
id: BOT-01
title: "Chatbot escalates to consultant on the first out-of-scope/small-talk reply instead of redirecting to reveal intent"
severity: medium
area: bot
labels: [bot-behavior, escalation, tingting-support, conversation-flow]
effort: M
status: todo
column: TODO
opened: 2026-09-28
---

# BOT-01 — Chatbot escalates to consultant on the first out-of-scope/small-talk reply instead of redirecting to reveal intent

**Severity:** medium · **Area:** bot · **Labels:** bot-behavior, escalation, tingting-support, conversation-flow

**Trạng thái:** TODO — reported 2026-09-28 from a production console screenshot (TingTing support OA, "Tư vấn viên" lane)

## Problem

On the TingTing support flow the bot escalates to a human consultant after a single
small-talk reply, without ever asking the user what they actually need.

Transcript from the 2026-09-28 production screenshot (employee "Frank Ng"):

| Time | Sender | Message |
| --- | --- | --- |
| 08:39 | user | `hi` |
| 08:39 | bot | `Anh/chị cần đặt lại mật khẩu ứng dụng TingTing phải không ạ?` |
| 08:40 | user | `hôm nay trời đẹp đấy` (small talk: "nice weather today") |
| 08:40 | bot | `Vui lòng chờ chuyên viên tư vấn liên hệ.` — immediate human handoff |

Console separator under the turn: `Luồng trích xuất đề nghị nhân viên xác minh ý định liên hệ.`
(the intent-verification extraction flow proposed the handoff).

The user never stated an intention. One weather comment and the conversation is
handed to a human. Expected: the bot should first try to surface the user's real
intention ("Anh/chị đang cần hỗ trợ gì ạ?"), and hand off only once it is clear the
user is just playing around.

## Evidence

Verified 2026-09-28 in the working tree:

- `backend/app/graph/tingting_guide.py:32` defines the handoff line:
  `TINGTING_CONSULTANT_HANDOFF_LINE = "Vui lòng chờ chuyên viên tư vấn liên hệ."`
- The support prompt (`backend/app/graph/tingting_guide.py:80-83`) orders an
  exact-verbatim handoff reply for anything outside the supported topics:
  «… nhân viên khác, hoặc bất kỳ chủ đề nào khác): trả lời ĐÚNG NGUYÊN VĂN một dòng
  … «Vui lòng chờ chuyên viên tư vấn liên hệ.»»
- The verify-intent rule (`backend/app/graph/tingting_guide.py:116-117`) is the one
  that fired in the screenshot:
  «Nếu câu trả lời không phải là việc đặt lại mật khẩu thì trả lời đúng dòng
  «Vui lòng chờ chuyên viên tư vấn liên hệ.» **và không làm gì thêm.**»
  i.e. any non-password-reset answer — including small talk — escalates instantly
  and forbids the model from doing anything else.
- Related context: `backend/app/graph/lanes.py:79-82` (`OUT_OF_SCOPE_PHONE_ASK`)
  shows a redirect-style reply already exists for the out-of-scope lane, and
  `plans/reports/260927-out-of-scope-consultant-handoff-completion.md` records the
  recently shipped out-of-scope handoff. The handoff itself is correct; what is
  missing is a redirect attempt before it for soft/no-intent messages.

## Impact

- Human consultants receive obvious small-talk/troll conversations ("hi", weather
  comments), wasting their time and diluting real escalations.
- Legitimate users who answer loosely ("không", "chuyện khác") get dumped to a
  silent handoff instead of being asked what they need — bad first impression on
  the support channel.
- The identity-verification flow's three-tries budget exists for verification, but
  intent discovery has no equivalent budget: one mismatch = escalation.

## Suggested fix

1. Add a redirect step in the TingTing support / verify-intent flow
   (`backend/app/graph/tingting_guide.py`): when the reply is not the expected
   intent AND carries no actionable request, reply with a short open question
   ("Dạ em chưa rõ ý anh/chị, anh/chị đang cần hỗ trợ gì ạ?") instead of the
   handoff line. Small talk answers to the redirect (weather, jokes, "hi" again)
   count as no-progress.
2. Escalate only after the redirect budget is exhausted — e.g. 2 consecutive
   no-progress replies after a redirect — or when the user explicitly refuses to
   state a need. Track the count in the existing turn/conversation state so the
   budget survives across turns and cannot loop forever.
3. Keep the immediate handoff for genuine out-of-scope requests (a real topic the
   bot cannot serve), for verification exhaustion, and for abuse — this card is
   only about the ambiguous/no-intent path.
4. Regression tests in `backend/tests/` (turn/router level, following
   `test_graph_runner_turn.py` conventions): small-talk reply → redirect reply and
   NO handoff line; small-talk twice after redirect → handoff line; explicit
   out-of-scope request → immediate handoff (unchanged).
5. **Approval gate:** the redirect wording lives in bot prompt/safety content, which
   AGENTS.md lists as approval-required. Get owner sign-off on the exact Vietnamese
   redirect line and the budget (2) before implementing.

## Notes

- Reported by the owner on 2026-09-28 with the production screenshot; no fix attempted.
- The screenshot also shows the bot guessed "password reset" from a bare `hi` — the
  guess itself is reasonable (it is the top support flow), the defect is what happens
  on the next non-matching turn.
- Related: `260927-2207-support-oa-clarify-handoff-fix-completion.md` (clarify/handoff
  fix on the same support flow) and `260927-out-of-scope-consultant-handoff-completion.md`.

---

_Opened 2026-09-28 from the owner's production report. All file/line references above checked on the live tree._
