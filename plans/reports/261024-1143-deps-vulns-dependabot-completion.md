# Agent Completion Checklist

## Task record

- Task: CHAT-2 — clear the 3 moderate Dependabot vulnerabilities on 4rankng/vfic-chatbot (frontend dependency chain).
- Scope: `frontend/package.json`, `frontend/package-lock.json`, vendored dependency stub `frontend/vendor/decode-uri-component/`, and the one `Dockerfile` COPY line the stub requires. No feature code.
- Files changed: `frontend/package.json`, `frontend/package-lock.json`, `frontend/Dockerfile`, `frontend/vendor/decode-uri-component/{package.json,index.js,index.d.ts,license}`, this report.
- Instructions retrieved: Root `AGENTS.md`, brief CHAT-2.
- Approval required: PASS — brief grants audit+fix+tests+commit+push; deploy explicitly excluded (orchestrator deploys after gates).

## Vulnerabilities addressed (GitHub Dependabot open alerts, verified via API 2026-10-24)

| Alert | Advisory | Package | Scope | Fix applied |
|---|---|---|---|---|
| #265 | GHSA-qxg6-89mg-rqv8 (medium) | `@vitest/mocker` ≤4.1.11 | dev | vitest family 4.1.11→4.1.12 (patch) |
| #264 | GHSA-xp26-3454-mjgp (medium) | `@vitest/mocker` ≤4.1.11 | dev | same patch bump |
| #194 | GHSA-vcc3-ghjq-m6fr (medium) | `decode-uri-component` ≤0.4.2 | runtime | override 0.2.2→0.5.1 algorithm, vendored as CJS |

The vitest bump is **dev-only, không ảnh hưởng runtime** (test tooling only).

### decode-uri-component: why vendored

- The existing `overrides` entry pinned `decode-uri-component: 0.2.2` — itself vulnerable (GHSA-vcc3-ghjq-m6fr covers ≤0.4.2); that pin is why `npm audit` reported "No fix available".
- Dependency chain: `ra-i18n-polyglot → ra-core → query-string@^7.1.3 → decode-uri-component@^0.2.2`. Even current ra-core 5.15.5 still requires `query-string ^7.1.3`, so no version bump can close the chain.
- Upstream publishes no fixed CommonJS build: 0.5.x (the patched line) is ESM-only. Drop-in override to 0.5.1 breaks the app: query-string 7.1.3 CJS-`require`s the decoder and calls it directly; the ESM namespace object makes every `query-string.parse()` throw `decodeComponent is not a function` — reproduced as 2 failing pagination tests in `list-table.test.tsx` (page stuck at 1 after "Trang tiếp").
- Fix: `frontend/vendor/decode-uri-component/` — upstream 0.5.1's patched O(n) algorithm (no ReDoS) converted to CJS, `module.exports` instead of `export default`. Behavior through query-string is unchanged: query-string 7.1.3 does its own `+`→space replacement before decoding (its `base.js` line 324), so 0.5.1 dropping the internal replace is transparent. Verified identical parse output on `+`, `%20`, malformed `100%`, and a stringify→parse round-trip.
- `frontend/Dockerfile` gained `COPY vendor ./vendor` before `npm ci` because `npm ci` resolves the `file:` override at install time.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | All 3 open Dependabot moderate alerts remediated; `npm audit` JSON shows the 3 target GHSA ids absent and `decode-uri-component` clean. |
| Diff is limited to the approved scope | PASS | `frontend/package.json`, `frontend/package-lock.json`, `frontend/Dockerfile` (one COPY line + comment), `frontend/vendor/decode-uri-component/*`, this report. No feature code touched. |
| Protected operations were avoided or approved | PASS | No deploy (`make deploy` not run, per brief), no secrets/auth/schema changes; commit+push explicitly requested. |
| Focused tests/checks pass | PASS | `npm audit`: 3 target advisories cleared (was 16 vulns overall → 7, none of them the ticket's 3). `npx vitest run --project app src/components/atomic-crm/kit/list-table.test.tsx`: 9/9 passed (was 2 failed with the broken override). Throwaway browser diagnostic confirmed `query-string.parse` works through the vendored build (identical output to 0.2.2 baseline) and reproduced `decodeComponent is not a function` with the raw 0.5.1 override; diagnostic deleted after use. |
| Broader regression tests pass when shared behavior changed | PASS | `npx vitest run`: 133 files, 1146/1146 tests passed. |
| Lint passes for affected code | PASS | `npm run lint -- --quiet` exited 0. |
| Type checking passes for affected code | PASS | `npm run typecheck` and `npm run typecheck:node` exited 0. |
| Build/import validation passes for affected code | PASS | `npm run build` completed; PWA precache 73 entries generated. |
| Security and privacy impact reviewed | PASS | The change removes GHSA-vcc3-ghjq-m6fr (runtime ReDoS decoder), GHSA-qxg6-89mg-rqv8 and GHSA-xp26-3454-mjgp (dev test-runner). No credential/PII surface changed. |
| Performance and async-I/O impact reviewed | PASS | Decoder is the same O(n) patched algorithm as upstream 0.5.1; no I/O changes. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. |
| Error handling and compatibility reviewed | PASS | Vendored decoder preserves upstream 0.5.1 semantics (malformed input like `100%` preserved literally, same TypeError on non-string); pagination tests cover the query-string boundary. |
| Documentation impact handled | PASS | Provenance header in `frontend/vendor/decode-uri-component/index.js`, comment on the Dockerfile COPY line, and this report record the durable vendoring decision. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. |
| Final `git diff --check` passes | PASS | `git diff --check` exited 0. |
| Final `git status --short` reviewed | PASS | Only the scoped files listed above plus this report. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - Out-of-scope advisories still open in `npm audit` (not among the 3 Dependabot alerts): `dompurify` ≤3.4.16 (critical, runtime, fixable within ^3), `zod` <4.6.6 (high, runtime, fixable within ^4), `shadcn` (high, dev CLI, fix needs major 3.x→4.x), `body-parser` (high), `fast-uri` (moderate), `ip-address` (moderate), `serialize-javascript` (low). Recommend a follow-up ticket for the runtime pair (dompurify/zod).
  - When `query-string` or `ra-core` eventually ships a chain that accepts `decode-uri-component` ≥0.5 as CJS-compatible, drop `frontend/vendor/decode-uri-component/` and the override together.
