---
id: DOC-07
title: "~21.2 MB of one-off marketing renders are tracked under assets/showoff"
severity: high
area: docs
labels: [documentation, tech-debt]
effort: S
status: doing
column: IN_PROGRESS
opened: 2026-09-24
---

# DOC-07 — ~21.2 MB of one-off marketing renders are tracked under assets/showoff

**Severity:** high · **Area:** docs · **Effort:** S · **Labels:** documentation, tech-debt

**Trạng thái:** IN_PROGRESS

## Problem

`assets/showoff/zalo-oa-architecture-flow/**` commits 18 PNGs at 0.87-1.9 MB each — every aspect-ratio × slide combination, uncompressed — for a one-time artifact with no runtime role. It is the single largest contributor to clone size.

## Evidence

- Six `horizontal-*.png` at 1.6-1.9 MB each (`images/horizontal-hero.png` 1.9 MB, `horizontal-recruiter-frontend.png` 1.8 MB, `horizontal-backend-brain.png` 1.8 MB, `horizontal-webhook-conduit.png` 1.7 MB, `horizontal-zalo-oa-bridge.png` 1.7 MB, `horizontal-e2e-flow.png` 1.6 MB) ≈ **10.25 MB**.
- Six `vertical-*.png` at 901 KB-1.0 MB ≈ **5.53 MB**; six `square-*.png` at 871-967 KB ≈ **5.28 MB**.
- Plus `index.html` 56.6 KB, `content.md` 10.1 KB and `capture.mjs` 3.1 KB → ≈ **21.2 MB** total, all tracked (`.git/index` `assets/showoff/…` = 21 entries / 1 subtree).
- [INFERENCE] The 55.1 MB pack is consistent with the current tree rather than a deleted giant blob, so this is live weight, not history.

## Impact

The largest single contributor to clone size and `.git` pack size, for an artifact no code reads; every aspect-ratio × slide combination is committed at 1-2 MB without compression.

## Suggested fix

Move the renders to object storage or a release artifact; if they must stay, keep only `.webp` at display resolution (~10× smaller) and `git rm --cached` the PNGs — `git rm -r --cached assets/showoff && printf 'assets/showoff/\n' >> .gitignore` once the files are archived elsewhere.

## Notes

Merge with DOC-06 — same `.gitignore` commit. Effort is M if the set is re-exported as webp.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
