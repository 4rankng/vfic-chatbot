---
id: TEST-22
title: "Add a timeout-minutes to the openwiki-update scheduled workflow"
severity: low
area: testing
labels: [ci, workflow, timeouts]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# TEST-22 — Add a timeout-minutes to the openwiki-update scheduled workflow

**Severity:** low · **Area:** testing · **Effort:** S · **Labels:** ci, workflow, timeouts

**Trạng thái:** TODO

## Problem

Every job in quality-gates.yml has an explicit timeout-minutes, but the scheduled openwiki-update job has none, so it inherits GitHub's 360-minute default. The job shells out to an LLM-driven CLI (openwiki against OpenRouter) on a cron; a hung API call burns a runner for up to 6 hours with contents:write permissions attached, and with no concurrency group overlapping daily runs can stack.

## Evidence

- .github/workflows/openwiki-update.yml:1-8 — triggers: workflow_dispatch and schedule cron '0 8 * * *'; the update job (line 10) has no timeout-minutes
- .github/workflows/openwiki-update.yml:25-28 — the openwiki step runs an external LLM CLI (openrouter model z-ai/glm-5.2) wrapped in continue-on-error, so a hang is invisible until the job budget expires
- .github/workflows/quality-gates.yml:20,70,127,173,260,286,386 — every quality-gates job sets timeout-minutes (20/45/20/30/20/20/15), making openwiki the only unbounded job

## Impact

A hung run occupies a runner for up to 6 hours; repeated hangs stack with the absent concurrency group.

## Suggested fix

Add `timeout-minutes: 30` (or 15) to the update job. The create-pull-request step already runs `if: ${{ !cancelled() }}`, so a timeout preserves the partial-progress PR behavior unchanged. Approval-gated (CI file).

## Notes

Failure propagation itself is handled correctly (propagate step re-raises after the PR step) — only the missing timeout is carded.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
