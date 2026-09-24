---
id: DOC-13
title: "frontend/public ships ~7.7 MB with the same login art committed three times"
severity: medium
area: docs
labels: [documentation, performance]
effort: S
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# DOC-13 — frontend/public ships ~7.7 MB with the same login art committed three times

**Severity:** medium · **Area:** docs · **Effort:** S · **Labels:** documentation, performance

**Trạng thái:** IN_PROGRESS

## Problem

Everything under `frontend/public/` is copied verbatim into the built image and served to browsers, yet it carries ~7.7 MB of masters and duplicates — four renderings of two login screens (≈2.47 MB) and multiple sizes of the same icons — against a VitePWA cache budget of ≤5 MiB.

## Evidence

- `login-recruiting-workspace.png` 2.0 MB + `login-recruiting-workspace.jpg` 302.4 KB + `login-recruiting-console-v2.webp` 69.7 KB + `login-mobile-workspace.jpg` 101.7 KB — four renderings of two login screens ≈ **2.47 MB**.
- `tinghire-icon-1024.png` 1.1 MB + `tinghire-icon-512.png` 189.5 KB + `tinghire-icon-192.png` 20.7 KB + `maskable_icon.png` 423.0 KB + `maskable_icon_x512.png` 147.4 KB, `ttsoft-logo.png` 868.8 KB, `bg.avif` 785.3 KB, `preview.png` 74.3 KB, plus `img/`, `brand/` and `appIcon/` (32 icons) — total ≈ **7.7 MB**.
- `frontend/Dockerfile` builds with node and serves from `nginx:1.27-alpine`, so everything under `public/` is copied verbatim into the image.
- `docs/codebase-summary.md:209` documents VitePWA with a ≤5 MiB cache budget — half-consumed by three copies of one hero image.

## Impact

Slower cold loads for Vietnamese mobile users on a droplet-hosted origin, and a PWA cache budget half-consumed by duplicate art.

## Suggested fix

Keep the `.webp`/`.avif` display sizes in `frontend/public/`, move masters (`*-1024.png`, `ttsoft-logo.png`, the `.png` login render) to `assets/` or a design repo outside the build path, and delete the `.jpg`/`.png`/`.webp` triplicate after confirming which are referenced.

## Notes

Merge with DOC-07 — both are asset-bloat removals and should land in the same pass.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
