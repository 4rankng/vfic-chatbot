# Trust post-mortem prompt smoke — 3 turns (Zalo, user Toàn shape)

Pipeline parts exercised for real: constraint gate → forced catalog tool →
server-pinned filter args → hard posture filter → tool payload; post-phone
STOP instruction; escalation short-circuit. LLM transport stubbed — the
candidate-facing prose on turns 1-2 is hand-authored to the injected
contract and marked SIMULATED; turn 3 is the code-authored fixed reply.

## Turn 1 — «cho em xin việc ngồi, đứng lâu không được»

- gate: `physical_constraint_filter` = `{'work_posture': 'seated'}`
- forced tool: `list_active_projects`
- pinned args (server-side, model cannot drop): `{'list_active_projects': {'work_posture': 'seated'}}`
- candidate set the LLM sees (post-filter): ['LG Display']
- 4P Electronics present? False
- unknown-posture project present? False
- route hint starts with the seated contract: True

BOT (SIMULATED per contract):

> Dạ với yêu cầu ngồi làm, hiện em có dự án LG Display (Hải Phòng) vị trí lắp ráp bo mạch được làm ngồi ạ. Anh/chị cho em xin số điện thoại để chuyên viên gọi tư vấn nhé ạ.

## Turn 2 — «Dạ số điện thoại của em là 0912 345 678 ạ»

- STOP instruction injected: True
- STOP flag in timings: True

BOT (SIMULATED per STOP contract):

> Dạ em đã nhận số điện thoại của anh ạ. Chuyên viên tuyển dụng bên em sẽ gọi lại hỗ trợ anh trong giờ hành chính nhé ạ.

## Turn 3 — «em bị gãy tay chân rồi, việc gì làm được không»

- escalation fired (route_reason=injury_escalation), model never ran (agent calls: 0)

BOT (CODE-AUTHORED, owner template):

> Dạ trường hợp này em chưa hỗ trợ được qua tin nhắn ạ. Anh/chị vui lòng gọi tổng đài miễn cước của VFIC theo số 1800 7228 để được nhân viên phụ trách trực tiếp hỗ trợ nhé ạ.

## Persona rules now in force (excerpt)

- identity honesty: True
- anti-repetition block in system prompt rules: True
- persona body carries no «không tự giới thiệu là bất kỳ thứ gì khác»: True

## Verdict: PASS
