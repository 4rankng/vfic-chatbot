# VFIC ATS Admin QA Test Plan

Last run: 2026-06-30

## Scope

Test the admin web app at `http://localhost:5173/` as an authenticated VFIC admin user. Cover real user workflows, responsive layout, visual regressions, accessibility basics, data mutation safety, and cross-resource navigation.

## Test Data Rules

- Use the provided admin account only for authentication.
- Create temporary records with a `QA` prefix and timestamped slug/email.
- Delete temporary records before ending the run.
- Never delete seed/business records such as `LG-DISPLAY` or real VFIC users.

## Auth

1. Visit `/`.
2. Verify unauthenticated users land on `#/login`.
3. Confirm login form renders email, password, show/hide password, submit, and forgot-password link.
4. Submit invalid credentials and verify a localized error toast.
5. Toggle password visibility and verify the input type changes and button label updates.
6. Submit valid admin credentials and verify redirect to dashboard.
7. Open account menu, verify profile/users/logout actions, then logout.
8. Visit forgot-password, submit a QA-only nonexistent email, and verify a generic recovery error/success response without exposing account existence.

## Navigation And Layout

1. Desktop routes render without blank states or console errors:
   - Dashboard
   - Leads
   - Conversations
   - Projects
   - Knowledge sources
   - Users
   - Bot runs
   - Personas
   - Profile
   - Changelog
2. Mobile routes render at 390 x 844 without horizontal overflow.
3. Mobile bottom navigation reaches Dashboard, Leads, Chat, and the More menu.
4. More menu exposes Projects, Knowledge, and Users.
5. Each mobile page has a semantic `main#main-content` landmark.
6. Desktop and mobile account menu triggers have accessible names.

## Dashboard

1. Verify health, delivery mix, knowledge pipeline, and ops attention sections render with live values.
2. Open the knowledge issue shortcut when a failed source is present.
3. Verify no chart/card overflows on desktop or mobile.

## Leads

1. Search by known candidate name and verify filtered count and URL filter state.
2. Search by a no-match QA string and verify empty state plus refresh action.
3. Clear search and verify the full list returns.
4. Open a lead card and verify detail modal content:
   - candidate identity
   - contact details
   - job/salary
   - stage/priority
   - recent messages
   - copy actions
5. Follow `Mở cuộc trò chuyện` and verify the matching conversation opens.
6. Open stage menu only if needed; if changed, restore the original stage before ending the run.

## Conversations

1. Verify conversation list, search box, pagination, selected conversation state, and empty state.
2. Open a conversation from lead detail and directly from the list.
3. Verify mode indicator and mode menu:
   - Human/recruiter
   - Semi-auto
   - Chatbot
4. In chatbot mode, verify composer is disabled.
5. Only send a test message in a dedicated QA conversation, never in a real candidate thread.

## Projects

1. Verify project dashboard metrics and selected project details.
2. Create a timestamped QA project.
3. Select it from the project picker.
4. Verify empty product-feature readiness state.
5. Edit the QA project name and verify list/detail refresh.
6. Delete the QA project and reload to confirm project count returns to baseline.
7. Confirm delete menus name the selected project before any destructive action.

## Knowledge

1. Search by known source text and verify filtered source count.
2. Search by no-match QA string and verify empty state.
3. Open upload dialog and verify:
   - template download controls
   - project selector
   - file-upload tab
   - paste-text tab
   - disabled upload button when empty
4. Enter sample paste text and verify upload button enables.
5. Cancel upload without creating a source unless a dedicated QA source cleanup plan is in place.
6. Verify source detail actions render: edit, retrain, download original, pipeline timeline.

## Users

1. Verify users list, table headers, status/role badges, sorting controls, and row action menu.
2. Submit create form empty and verify validation/error feedback.
3. Create a timestamped QA user.
4. Verify QA user appears in the table.
5. Edit QA user full name and verify table update.
6. Delete only the QA user and verify it is removed.
7. Confirm destructive dialog names the target account.

## Profile

1. Open profile from account menu.
2. Verify account details render.
3. Edit display name and confirm Save starts disabled, then enables after a change.
4. Save a temporary value, re-open, restore original value, and verify success toast.

## Bot Runs And Personas

1. Open bot runs list and verify run cards render outcome, message preview, and timing.
2. Open a bot run detail if available.
3. Open personas list and verify active persona is marked.
4. Open persona detail/edit only if changes can be safely restored.

## Changelog

1. Open changelog from URL or account/menu entry.
2. Verify content is VFIC-specific and does not expose upstream Atomic CRM release notes.

## Automated Checks

- Run `npm run typecheck` from `frontend/`.
- During browser QA, inspect console errors on every route.
- For responsive QA, assert `document.documentElement.scrollWidth <= window.innerWidth + 2`.

## Current Run Summary

- Passed: login/logout, invalid login, password visibility, forgot-password page, dashboard, desktop route health, mobile route health, mobile More menu, lead search/detail/deep-link, conversation mode menu, knowledge search/upload dialog, user create/edit/delete, project create/edit/delete cleanup, profile edit/restore, theme toggle.
- Fixed: unlabeled account menu trigger, missing mobile `main` landmark, inherited Atomic CRM changelog content.
- Known data issue observed: dashboard reports one failed knowledge source, `faq-001-lg-display.md`, with `TypeError: 'coroutine' object is not subscriptable`; this appears to be real pipeline data surfaced by the app, not a frontend rendering bug.
