---
id: BOT-03
title: "TingTing support persona re-pitches the password-reset flow on social closers/gibberish after the issue is already resolved"
severity: medium
area: backend
labels: [chatbot, tingting, prompt, ux]
effort: S
status: todo
column: TODO
opened: 2026-09-28
---

# BOT-03 — TingTing persona re-pitches password reset after resolution

**Severity:** medium · **Area:** backend · **Labels:** chatbot, tingting, prompt, ux

**Trạng thái:** TODO — owner approved the fixed wording and rule 2026-09-28.

## Problem

Production 2026-09-28, TingTing OA, employee Trần Quang Việt: "e đăng nhập dc rui" → the
bot correctly closed ("không cần đặt lại mật khẩu nữa ạ"). The employee then sent "ô sò kề"
(a casual closer ≈ "ô kê") at 18:07 and again at 18:09 — and the bot answered BOTH with the
unclear-intent redirect pitching the password-reset flow
("Dạ em chưa rõ ý anh/chị. Nếu anh/chị cần hỗ trợ đặt lại mật khẩu ứng dụng TingTing…").
The conversation had just resolved; the employee was socializing, not asking for support.

## Root cause

`backend/app/graph/tingting_guide.py` — the support persona's unclear-intent rule
(added in BOT-01, lines ~85-88) buckets greetings, social messages, "ok", "rồi" and
unreadable messages as "CHƯA RÕ nhu cầu" → ask the confirm question / send
TINGTING_INTENT_REDIRECT_REPLY. The rules model "before clarity" but have no
**post-resolution state**: once the issue is resolved (or the confirm question was already
asked once), closers and gibberish should get a warm close, not another pitch. Nothing
caps consecutive unclear-intent asks either, so the same pitch repeated twice in 2 minutes.

## Design (owner-approved 2026-09-28)

1. New operator-approved fixed reply, verbatim:
   `TINGTING_RESOLVED_CLOSER_REPLY = "Dạ không có gì ạ, em luôn đây khi anh/chị cần hỗ trợ 😊"`
2. Rule: when the issue has been resolved — or the confirm question was already asked once
   and the employee replies with thanks/OK-style closers/gibberish instead of engaging —
   reply with the fixed closer. Never re-pitch the reset flow in that state.
3. The reset flow re-engages only when the employee again mentions password/login trouble
   (or asks for a reset). The confirm question may appear at most once per conversation
   after resolution.
4. The existing escalation budget in lanes stays untouched as the backstop.

## Suggested fix

- Extend the persona rules in `TINGTING_SUPPORT_PERSONA` (and the guide's fixed-reply
  section) in `backend/app/graph/tingting_guide.py`. Keep the wording of the new closer
  exactly as approved. Check whether TINGTING_INTENT_REDIRECT_REPLY / TINGTING_CONFIRM_REPLY
  are emitted from any deterministic code path outside the guide (grep usages) — if such a
  path needs the once-only guard in another file, STOP and report; do not edit
  context.py/lanes.py/proactive.py (another teammate owns them right now).
- Tests: closer reply used for post-resolution social/gibberish turns; reset flow still
  starts when login trouble is mentioned again; existing tingting guide tests updated.

## Notes

- Runs in parallel with BOT-02 (disjoint files). Same verification gates:
  focused tingting/graph tests, pyright app/graph = 0 errors, ruff.

---

_Opened 2026-09-28 from the Trần Quang Việt screenshot; owner approved wording same day._
