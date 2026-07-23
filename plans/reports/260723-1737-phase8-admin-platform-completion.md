# Agent Completion Checklist

- Task: Phase 8 admin/platform slice
- Date: 2026-07-23
- Scope: frontend auth refresh, installation runtime manifest boundary, integration gateways/helpers, docs drift

## Completion Gate

### 1. Build passes
- `BLOCKED` Frontend build not run in this slice because repo-wide typecheck is already failing outside owned files (`knowledge/infrastructure/http-knowledge-adapter.ts`, `leads/application/loadRecruitmentConversationRows.ts`, `personas/infrastructure/personaActionsApi.ts`).

### 2. All tests pass
- `PASS` `frontend/npm run test:unit:app -- src/components/atomic-crm/providers/rest/api.refresh.test.ts src/components/atomic-crm/installation/runtime-manifest.test.ts src/components/atomic-crm/installation/runtime-manifest-application.test.ts src/components/atomic-crm/installation/InstallationBootstrap.test.tsx src/components/atomic-crm/integrations/FacebookMessengerIntegrationPage.test.tsx src/components/atomic-crm/integrations/ZaloIntegrationPage.navigation.test.tsx src/components/atomic-crm/integrations/ZaloIntegrationPage.test.ts` → 7 files, 59 tests passed.

### 3. No lint errors
- `PASS` `frontend/npm run lint -- src/lib/apiClient.ts src/components/atomic-crm/installation/runtime-manifest.ts src/components/atomic-crm/installation/runtime-manifest-policy.ts src/components/atomic-crm/installation/runtime-manifest-application.ts src/components/atomic-crm/installation/runtime-manifest-browser.ts src/components/atomic-crm/installation/runtime-manifest.test.ts src/components/atomic-crm/installation/runtime-manifest-application.test.ts src/components/atomic-crm/installation/InstallationBootstrap.test.tsx src/components/atomic-crm/integrations/api.ts src/components/atomic-crm/integrations/facebook-oauth-callback.ts src/components/atomic-crm/integrations/FacebookMessengerIntegrationPage.tsx src/components/atomic-crm/integrations/FacebookMessengerIntegrationPage.test.tsx src/components/atomic-crm/integrations/ZaloIntegrationPage.tsx src/components/atomic-crm/integrations/ZaloIntegrationPage.navigation.test.tsx src/components/atomic-crm/integrations/ZaloIntegrationPage.test.ts`

### 4. No type errors
- `BLOCKED` `frontend/npm run typecheck` fails outside owned files:
  - `src/components/atomic-crm/knowledge/infrastructure/http-knowledge-adapter.ts`
  - `src/components/atomic-crm/leads/application/loadRecruitmentConversationRows.ts`
  - `src/components/atomic-crm/personas/infrastructure/personaActionsApi.ts`

### 5. Documentation updated
- `PASS` Updated `docs/codebase-summary.md` and `docs/system-architecture.md` to reflect the fixed static recruitment runtime and removed stale compiler/parity wording.

### 6. No TODOs without linked issues
- `PASS` No new TODO/FIXME/HACK markers added in owned files.

### 7. Migration reviewed (if any)
- `N/A` No migration changes.

### 8. Performance checked
- `PASS` Concurrent 401 refreshes now share one in-flight refresh promise; installation runtime fetch still enforces `no-store` and timeout behavior.

### 9. Security reviewed
- `PASS` No secrets exposed or logged; blank-secret keep behavior preserved; OAuth popup still uses `noopener`; runtime manifest public projection remains validated and unauthenticated.

## Additional Verification

- `BLOCKED` `backend/.venv/bin/python -m pytest tests/test_architecture_boundaries.py -q` fails on an unrelated existing edge:
  - `product_lib|frontend/src/components/atomic-crm/leads/infrastructure/leadRealtime.ts|frontend/src/lib/vfic/realtimeSocket`
