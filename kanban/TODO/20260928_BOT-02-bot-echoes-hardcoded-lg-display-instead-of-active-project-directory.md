---
id: BOT-02
title: "Bot echoes the hardcoded LG Display example on company-identity and vague job-seek turns instead of the active-project directory"
severity: medium
area: backend
labels: [chatbot, prompt, projects, advertising, grounding]
effort: M
status: todo
column: TODO
opened: 2026-09-28
---

# BOT-02 — Bot echoes the hardcoded LG Display example instead of the active-project directory

**Severity:** medium · **Area:** backend · **Labels:** chatbot, prompt, projects, advertising, grounding

**Trạng thái:** TODO — design settled in the 2026-09-28 lead interview; implementation approved by the owner.

## Problem

Production 2026-09-28, candidate 4553 asked "Cty ở đâu vậy". The bot answered the VFIC
office correctly, then advertised exactly one workplace: "các vị trí tuyển dụng của VFIC
hiện tại là làm việc tại nhà máy LG Display, thuộc KCN Trảng Duệ, An Dương, Hải Phòng".
The project directory actually knows four seeded projects (LG Display Hải Phòng,
LG Display Bắc Ninh, Samsung Bắc Ninh, Foxconn Nghệ An), so the single-project answer
under-advertises and anchors every undecided candidate to one factory.

## Root cause (verified 2026-09-28)

- `backend/app/graph/context.py:31` — the company-identity fixed-facts block (which the
  prompt says to answer from WITHOUT any tool call) contains the parenthetical
  "(ví dụ LG Display) làm việc tại nhà máy LG Display, KCN Trảng Duệ, An Dương, Hải Phòng".
  The model echoes the example verbatim. The rest of the machinery is fine:
  `active_projects_index()` (context.py:94-132) already renders every active project
  (slug, name, summary, aliases, roles, location) into the preamble, Redis preamble-cached,
  `list_active_projects`/`list_active_jobs` are bound on general consult turns, and rows are
  admin-managed (atomic-crm ProjectList/ProjectShow) with LLM-generated index cards.

## Design (settled with the owner 2026-09-28)

1. **Trigger (passive):** the bot presents active projects when the candidate is unsure
   which jobs exist or is vaguely looking for work, and on company-identity questions.
   No new router intent; a prompt rule + the always-present directory.
2. **Fields:** name + plant location + highlights (xe đưa đón, KTX/chỗ ở, mốc lương tham
   chiếu) — directory lines should render `index_card` highlights. "Is hiring" is NOT a
   project field; hiring claims stay anchored to `list_active_jobs` evidence.
3. **Grounding: strict.** Every project-specific claim must come from the directory or
   published KB text. Empty highlight fields → the bot says only name + location and offers
   the consultant callback. No invented benefits, ever (see the adapters.py:266 scar).
4. **Fixed facts:** strip the LG example from context.py:31; keep the VFIC office facts and
   the office-vs-plant PHÂN BIỆT BẮT BUỘC rule; defer project enumeration to the directory.
5. **Scope:** all channels EXCEPT the TingTing OA (`account_key="tingting"` stays pure
   support). Other OAs behave identically.
6. **Seed typo:** `samsung-bac-ning` → fix only if nothing references the slug; otherwise
   record and leave (prod-DB slug coupling).

## Suggested fix

- Rewrite the context.py:31 sentence per (4) and add the vague-seeker rule per (1),
  pointing at the DANH MỤC block.
- Render `index_card` highlights in the directory line per (2), sourced only from the card.
- Gate the directory injection (and vague-seeker rule) off for the TingTing account per (5).
- Tests: directory line rendering (with/without highlights), TingTing gate, fixed-facts
  content contains no project example, vague-seeker rule present. Run graph-focused suites,
  pyright (`app/graph` must stay at 0 errors), ruff.

## Notes

- The directory is preamble-cached — a cache bump already happens on card writes
  (project_index_repository.py:53,85); the rule-text change must respect that cache path.
- This surface is approval-gated (bot prompt/safety): approval = owner instruction in the
  2026-09-28 interview.

---

_Opened 2026-09-28 from the candidate-4553 screenshot and the lead design interview._
