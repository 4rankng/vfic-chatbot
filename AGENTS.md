# AGENTS.md — Ting Ting Engineering Constitution

This is the small, always-loaded contract for coding agents. Identify the task
surface, then retrieve only the instructions and neighboring files needed for
that task — do not preload the whole documentation tree. Project instructions
override global instructions.

## Sources of truth

- Repository map: `docs/product/codebase-summary.md`
- Architecture: `docs/architecture/system-architecture.md`
- API reference: `docs/architecture/api.md`
- Code conventions: `docs/development/code-standards.md`
- Testing: `docs/development/testing.md`
- Agent harness and hooks: `docs/architecture/agent-development-kit.md`
- Completion record: `standards/agent-completion-checklist.md`

`.claude/` is machine-local and untracked (see `.gitignore`), so nothing under
it is a source of truth — every durable rule lives in the tracked sources
above. For backend, frontend, security, performance, deployment, or bot work,
load the matching source above or the task-routing source below. Do not
retrieve unrelated instructions "just in case."

## Non-negotiable boundaries

- API transport belongs in `backend/app/api/`. Framework-free policy and value
  contracts belong in each layer slice's `domain/`, orchestration and ports in
  its `application/`, and shared cross-slice workflows in
  `backend/app/services/`. The dependency matrix between those layers is
  machine-enforced with zero exceptions by
  `backend/tests/test_architecture_boundaries.py` — read it before adding a
  cross-layer import; it fails `make release-check` when violated.
- Bot-turn behavior belongs in `backend/app/graph/`. `runner.py` drives the
  turn; each stage module beside it holds one stage and depends on the
  Protocols in `backend/app/graph/ports.py`. Wire concrete dependencies only
  in `backend/app/graph/factories.py` and `backend/app/composition/`, never
  inside a domain or application module.
- Conversation orchestration belongs in
  `backend/app/services/conversation/`. `service.py` is the entry point and
  stays orchestration-only: the reconcile SQL and recruiter receipt writes
  live in the leaf modules beside it.
- Models mirror the hand-written Alembic schema in
  `backend/alembic/versions/`; they do not generate migrations.
- Frontend dependency direction is `atomic-crm` → `admin` → `ui`; product
  code belongs in `frontend/src/components/atomic-crm/`.
- Keep I/O async, avoid raw SQL outside Alembic and circular imports, and
  offload blocking crypto.
- LLM calls go through `backend/app/graph/clients.py`.
- Use structured logging through `backend/app/core/logging.py`; never log
  secrets, PII, or message content.
- Preserve public contracts and unrelated user changes unless approved scope
  says otherwise. Never add fake production behavior or weaken checks.

## Scoped workflow

1. Inspect `git status`, relevant neighboring files, and `plans/` for overlap.
2. State artifacts, acceptance criteria, exclusions, and approval gates.
3. Retrieve only task-relevant instructions. Use existing patterns and the
   smallest complete change; prove bug causes and add regression tests.
4. Run the narrowest relevant check, broadening only for shared behavior or
   contracts. Never hide failures.
5. If you change what this file or the routed documents point at, run
   `node scripts/check-doc-links.mjs` before finishing.
6. Copy `standards/agent-completion-checklist.md` to
   `plans/reports/<date>-<slug>-completion.md` and fill every gate with
   `PASS`, `N/A`, or `BLOCKED` plus evidence before declaring completion.
7. Update docs only for user-visible behavior, setup, commands, architecture,
   security posture, public contracts, or durable maintainer decisions.

Do not deploy, commit, push, merge, open a PR, or create a branch unless asked.
When asked to commit, work directly on `main` per the repository workflow.

## Task routing

- Implementation: `docs/development/code-standards.md`
- Verification: `standards/review-checklist.md`
- Dev-environment QA: `standards/agent-completion-checklist.md` (record only)
- UI/UX design problems: `frontend/AGENTS.md` → "UI/UX Component Sourcing".
  Consult the Untitled UI and Tailkit MCPs before hand-writing markup.
- Bot diagnosis: `docs/troubleshooting/chatbot-response-path.html`
- Deployment: read `docs/ops/deployment-guide.md` in full, then obtain
  approval. `make deploy` is blue/green and smoke-gated
  (`backend/scripts/smoke_turn.py`); `make -C backend rollback` flips back to
  the previous color/tag without a rebuild.

Use `standards/definition-of-done.md` and `standards/review-checklist.md` only
when their detailed gates apply to the task.

## Board tickets — plan.tingting.vip (bắt buộc từ 24/10)
MỌI thay đổi code bắt nguồn từ request/complaint/feedback PHẢI có issue trên board TRƯỚC khi code; commit message cite ticket (vd CHAT-123).

- Board: https://plan.tingting.vip/tingtingsoft/CHAT
- Quản lý qua MCP JSON-RPC: `POST https://plan.tingting.vip/mcp` với headers
  `Authorization: Bearer $(cat ~/.hermes/profiles/dev/cache/scratch/ttplan-token.txt)`
  và `Accept: application/json, text/event-stream`.
  Flow: `initialize` (giữ header Mcp-Session-Id từ response) → `notifications/initialized` → `tools/call`.
- Tools hay dùng: `list_issues {projectKey:"CHAT"}` (mỗi call = 1 page — lặp với seen-id set)
  · `create_issue {projectKey, columnId, title, description}`
  · `update_issue {issueId, columnId}` để chuyển cột (KHÔNG dùng move_issue — đó là đổi project)
  · `add_comment {issueId, body}`.
- Cột của CHAT: Backlog=11 · Todo=12 · In Progress=13 · Done=14 · Canceled=15.
- Luật chuyển cột: mọi chuyển PHẢI kèm `add_comment` evidence (Done = có evidence kiểm chứng;
  Canceled = won't-do + ghi rõ ruling/owner decision). Không đổi trạng thái khi thiếu evidence.

## Consultation — webchat (design/UI/UX/SDLC)
Khi gặp quyết định design/UI/UX, lựa chọn kiến trúc/library, hoặc challenge SDLC chưa rõ hướng:
consult webchat TRƯỚC khi tự quyết:
```bash
cd /Volumes/LexarSSD/projects/one-shot
timeout 240 python3 tools/webchat.py gemini send "<câu hỏi + NGỮ CẢNH + số liệu cụ thể>"
sleep 60 && timeout 120 python3 tools/webchat.py gemini capture   # lặp nếu câu trả lời dài
```
- Adapter gemini/deepseek ONLY. Gửi kèm constraint + số đo thật (px, test counts, spec gốc).
- Pattern/verdict trả về phải được dẫn lại trong brief hoặc comment ticket.

## COMPLETION PROTOCOL (lane land xong — bắt buộc 24/10)
Khi công việc đã commit + push thành công:
1. Update ticket trên board: `update_issue {issueId, columnId:<Done>}` + `add_comment` evidence: commit hash, số test pass, gates.
2. Notify Hermes orchestrator NGAY (không đợi bị hỏi):
   `hermes send --to telegram "✅ <MÃ-TICKET> landed <hash> — <1 dòng tóm tắt> · tests <n>/<n>"`
3. Chỉ khi 2 bước trên xong mới được kết thúc lane. Nếu board/Telegram lỗi → ghi rõ trong HANDOFF.md phần \"COMPLETION BLOCKED\" kèm lý do.
