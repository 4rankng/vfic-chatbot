---
id: FE-25
title: "Sync registry.json dependencies block with package.json before next registry:build"
severity: low
area: frontend
labels: [ops, registry, dead-config]
effort: S
status: todo
column: TODO
opened: 2026-09-26
---

# FE-25 — Sync registry.json dependencies block with package.json before next registry:build

**Severity:** low · **Area:** frontend · **Effort:** S · **Labels:** ops, registry, dead-config

**Trạng thái:** TODO

## Problem

The registry generator preserves whatever dependencies array is checked in (it only rewrites files and spreads the rest of the item), so the manifest still lists the upstream atomic-crm dependency set even though package.json dropped them and no src file imports them. Anyone installing the published block gets 11 dead packages; the drift is invisible to the registry:check gate, which validates paths and local imports only.

## Evidence

- frontend/registry.json:19-33 — items[0].dependencies advertises @hello-pangea/dnd, @nivo/bar, faker, papaparse, jsonexport, @streamparser/json-whatwg, mime, ra-supabase-core, ra-supabase-language-english, @tanstack/query-async-storage-persister, @tanstack/react-query-persist-client
- frontend/package.json:36-80 — none of those packages appear in dependencies; repo-wide grep for nivo|faker|jsonexport|streamparser|papaparse|hello-pangea in frontend/src returns zero imports
- frontend/scripts/generate-registry.mjs:78-90 — the generator rewrites only the files array and spreads ...item otherwise, so the stale dependencies list can never self-heal
- frontend/scripts/check-registry-paths.mjs:20-42 — the CI-enforced checker validates manifest paths, duplicates, and test-file leaks but never inspects the dependencies array

## Impact

Running npm run registry:build publishes a block whose install list pulls heavy unused packages (nivo, faker, dnd) into consumer apps and references ra-supabase adapters this fork replaced.

## Suggested fix

In generate-registry.mjs, derive dependencies from package.json (intersected with what registry files import, or simply replace the hardcoded list) and regenerate registry.json; at minimum hand-edit registry.json:19-33 down to the packages the registry files actually import (zod, marked, dompurify).

## Notes

File-path half is already safe: quality-gates.yml:154-155 runs npm run registry:check — only the dependencies block drifts.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
