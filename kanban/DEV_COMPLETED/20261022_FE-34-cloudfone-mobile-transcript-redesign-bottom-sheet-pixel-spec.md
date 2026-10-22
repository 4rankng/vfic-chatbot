---
id: FE-34
title: "Cloudfone mobile transcript redesign — bottom-sheet pixel-spec (salvage lane 0afc452)"
severity: low
area: frontend
labels: [frontend, cloudfone, mobile, redesign, qa-harness]
effort: M
status: dev-completed
column: DEV_COMPLETED
opened: 2026-10-22
---

# FE-34 — Cloudfone mobile transcript redesign — bottom-sheet pixel-spec

**Severity:** low · **Area:** frontend · **Effort:** M · **Labels:** frontend, cloudfone, mobile, redesign, qa-harness

**Trạng thái:** DEV_COMPLETED (salvage-close)

## Problem

Mobile transcript viewer không theo pixel-spec: bottom-sheet không snap 50%/92% theo visual-viewport, bubble layout/speaker labels sai, error/empty states thiếu sub-copy + retry.

## Changes (main 23bd1e7e)

- `bottom-sheet.tsx` — snap heights theo `--visual-viewport-height` (50% ↔ 92% drag)
- `CloudfoneTranscriptsSection.tsx` + `TranscriptConversation.tsx` + `cloudfone-transcripts.css` — mobile list/sheet/header meta (duration • date), bubbles S1 left / S2 right + labels, error & empty sub-copy, retry reload
- `qa/2026-10-22-cloudfone-redesign/drive.mjs` — UI-driven QA: port hygiene, seed cf-qa-1..4, desktop evidence shot (newContext+storageState, day=2026-10-21, text locator — phone cells không có role=cell)

## Evidence

- Scoped vitest: 2 files / **23 tests passed**; tsc app + node: **0 errors**
- QA drive (LOCAL :8000/:4173): **ALL PASS — 6 screenshots** (01 mobile list → 06 desktop table+panel), all /api/v1 calls 200

## Notes

- Lane do provider crash chết lúc finish line (agent 0afc452, glm-5.3, "OpenCode helper server exited"); work salvage qua guard commit `b6438e92` + fix harness `0fe6bf05`/`96579b9a`, venv symlink junk dropped `03c066e5`.
