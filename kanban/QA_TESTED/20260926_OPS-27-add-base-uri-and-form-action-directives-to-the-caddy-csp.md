---
id: OPS-27
title: "Add base-uri and form-action directives to the Caddy CSP"
severity: low
area: ops
labels: [security, csp, edge]
effort: S
status: done
column: QA_TESTED

opened: 2026-09-26
---

# OPS-27 — Add base-uri and form-action directives to the Caddy CSP

**Severity:** low · **Area:** ops · **Effort:** S · **Labels:** security, csp, edge

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

The deployed CSP covers default-src, object-src, frame-ancestors, style-src, font-src and img-src, but omits base-uri. Per the CSP spec base-uri does NOT fall back to default-src, so a page without it accepts an injected `<base href>` tag, which redirects every relative fetch and can defeat same-origin assumptions. form-action currently falls back to default-src 'self'; making it explicit protects against a future relaxation of default-src.

## Evidence

- backend/Caddyfile.template:22 — full CSP string has no base-uri and no form-action
- backend/Caddyfile.template:6-10 — this template is the single source of the edge config; flip_caddy.sh renders it, so the fix lands in one file
- backend/app/main.py:202 — TrustedHostMiddleware with an explicit host list shows host/URL manipulation is already treated as in scope (SEC-06 lineage)

## Impact

If any HTML-injection foothold appears (a compromised npm dependency is the realistic path given the SPA ships inline scripts), an injected `<base>` can silently reroute same-origin fetches. Zero functional cost to close: no form posts and no `<base>` usage exist in the SPA today.

## Suggested fix

Extend the Content-Security-Policy value at Caddyfile.template:22 with `base-uri 'self'; form-action 'self';` (consider upgrade-insecure-requests), then redeploy the edge via flip_caddy.sh. No app changes required.

## Notes

Re-verify style-src/img-src in a browser per the SEC-06 residual note before relying on the expanded header as a control.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
