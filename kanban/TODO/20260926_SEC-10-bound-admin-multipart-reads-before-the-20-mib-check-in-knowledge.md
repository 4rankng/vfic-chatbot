---
id: SEC-10
title: "Bound admin multipart reads before the 20 MiB check in knowledge.py and personas.py upload routes"
severity: low
area: security
labels: [security, uploads, hardening]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# SEC-10 — Bound admin multipart reads before the 20 MiB check in knowledge.py and personas.py upload routes

**Severity:** low · **Area:** security · **Effort:** S · **Labels:** security, uploads, hardening

**Trạng thái:** TODO

## Problem

Three admin multipart upload routes call `await file.read()` on the full request body before enforcing MAX_UPLOAD_BYTES = 20 MiB. Starlette spools bodies over ~1 MiB to a temp file, but .read() pulls the entire body into RAM in one allocation before the cap check runs. The SEC-05 lesson already produced the right patterns elsewhere — webhooks.py checks Content-Length before reading, and projects.py:316 does a bounded read — but knowledge.py and personas.py never got them. Caddy sets no request_body limit either, so nothing upstream bounds the body.

## Evidence

- backend/app/api/knowledge.py:170-171 — upload_kb_version_file does `data = await file.read()` before _reject_oversized_upload(data)
- backend/app/api/knowledge.py:396-397 — upload_file (documents/upload-file) repeats the unbounded read-then-check
- backend/app/api/personas.py:166-170 — import_persona reads fully then assert_upload_size(len(data)); the comment claims it prevents buffering, but the read already completed
- backend/app/api/projects.py:316-317 — the correct pattern: `raw = await file.read(500_001)` bounded read before the size check
- backend/app/api/webhooks.py:83-103 — _read_body_within_limit checks Content-Length before request.body(); never applied to the upload routes
- backend/docker-compose.yml:116,149 — web-blue/web-green memory limits 384M are the only backstop for the active web color

## Impact

An admin account (or a hijacked admin session) can OOM-kill the active web color mid-request: latency spikes for every user, blue/green has no automatic flip on OOM, and repeated posts can fill the droplet disk via spool files. Bounded by the admin-only gate — hence low — but the fix is three one-line edits.

## Suggested fix

Replace `await file.read()` with `await file.read(MAX_UPLOAD_BYTES + 1)` at knowledge.py:170 and :396 and personas.py:166 (mirroring projects.py:316), optionally hoisting a Content-Length precheck like webhooks.py:87-96. Extract the shared _reject_oversized_upload helper to app/services/ingestion/limits.py so personas.py reuses it.

## Notes

api/ routes are transport surface — allowed to edit without extra approval, but verify the three routes' error contracts stay identical.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
