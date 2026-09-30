# Release gate, ingest stall, and listing-style fixes

Date: 2026-09-30 (Asia/Singapore) · Three defects found during the 30/09 deploy
and the brief-import smoke test, all fixed, deployed, and verified on prod.

## 1. `make release-check` failed while the golden gate passed

Symptom: gate printed `release gate passed` yet make exited 1; the pasted tail
only showed the data lane. The three-lane recipe prints each lane's log with its
exit code, and the temp dir is deleted afterwards, so the failing lane had to be
reproduced with full output captured.

Root cause: `test_frontend_domain_and_application_layers_do_not_use_browser_io_globals`
matched its `\bdocument\s*\.` style regexes against comment prose — sentences
ending in "document." in the new `projects/domain` and `projects/application`
files — not actual browser-global usage. Fix (06f5d417): strip `/*…*/` and
`//…` comments before matching, matching the gate's stated intent; verified
prose no longer trips it and a negative control (real `document.cookie` /
`fetch(` in code) still does.

## 2. Brief import "stuck" at «Chỗ ở» (6/12)

Symptom: three projects' category loops appeared frozen at different positions.
Backend evidence contradicted the UI: every recent revision `ACTIVE`, queues
drained, worker logs healthy. Category jobs complete in 5–15s, but the same
single `ingest` queue also carried multi-minute document ingests
(`run_ingest_job` ≈ 2.5 min), and a category job queued behind one waited the
full duration (revision created 06:41:55, processed 06:44:13). Twelve
serialized activations interleaved with two document ingests ≈ half an hour of
apparent silence.

Fix (79483cb6): category revisions enqueue on their own `category` queue and
worker-ingest runs `rq worker category ingest` — RQ drains queues in listed
order, so UI-blocking activations always preempt heavy ingestion. Boot queue
snapshot in `main.py` includes `category`; the compose contract and enqueue
tests pin the new wiring. Known debt left deliberate: external-source sync and
direct-context jobs still share `ingest` (not UI-serialized); move them only if
they grow a latency contract.

## 3. Bot dumped every role row on overview questions

"Có bao nhiêu dự án đang tuyển" produced a 10-row per-role list, contradicting
the persona's own ~300-character rule. Persona is code-embedded
(`backend/app/graph/persona.md`, loaded at import; no admin upload surface
exists). Fix (e05b98f0): new persona section — overview questions answer the
exact `total`, then one line per project (name, area, headline salary); the
full per-job template is reserved for a narrowed question; close with one open
question (area/role/salary/shift). Owner can reword the section directly.

## Unrelated answer

`job_ids: []` in category YAML is the schema's role-association affordance; the
API validates references against active jobs (why `jobs` activates first). The
brief planners emit `[]` because brief content is project-wide, not
role-resolved.

## Deploy evidence

Three green releases this session (06f5d417, e05b98f0 intermediate, final
`e05b98f0` on blue, `PREV=green@06f5d417`). Smoke-gated flips passed; post-flip
readiness all healthy with 0 restarts; `/healthz`, `/health`, `/` all 200 from
outside the host; prod worker logs `Listening on category, ingest...` in that
order. Backups landed in OneDrive per deploy as designed.
