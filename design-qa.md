# Design QA

## Prior performance-dashboard validation

Selected design direction: diagnostic matrix (Image Gen option 2), based on the
existing `/hieu-suat` screen and the light Ting Ting workspace system.

- Typecheck, lint, and production build passed.
- The authenticated local route rendered successfully with an admin session.
- Window control, refresh, empty states, populated telemetry, and the prior
  390 × 844 mobile presentation were verified.

The local seed includes healthy, warning, and failure telemetry for future
performance-page reviews.

## Current mobile-native redesign

- Source visual truth: `/Users/dev/.codex/generated_images/019f57ad-4c82-7a10-856f-d646d4421c44/exec-3a547db6-993a-4b3b-a041-861fa8ee3232.png` (selected option 2).
- Intended viewport set: iPhone 15 Pro, iPhone SE, Pixel 8, and Galaxy S23.
- Intended states: dashboard empty and candidate-row states; project selection and actions; Zalo credential disclosure and connection test; performance metric rail and diagnostic disclosures; bottom-navigation active and overflow states.

## Evidence gap

Chrome’s automation connection returned `Browser is not available: extension` before any live page could be opened. Consequently, no browser-rendered implementation screenshot, device capture, interaction test, console check, or visual comparison can be produced in this session.

## Static validation completed

- `npm run typecheck` — passed.
- `npm run lint` — passed.
- `npm run test:unit:app` — 29 files / 219 tests passed.
- `npm run build` — passed.

## Required browser verification after Chrome is connected

1. Capture every affected route before/after at the four target viewports.
2. Verify dashboard candidate navigation and empty-state density.
3. Verify project selection, edit menu, create/upload actions, and quick-stat truncation.
4. Verify settings disclosures, masked-field reveal/copy controls, clipboard behavior, and inline tests.
5. Verify metric carousel scrolling, window selection, slow-turn details, and one-at-a-time diagnostic disclosures.
6. Verify fixed navigation, safe-area spacing, overflow sheet, keyboard focus, and no horizontal overflow.

Archived prior result: blocked

---

## Current conversation-header density correction

- Source visual truth: `/var/folders/8j/qs8k8y3n1hlfbl4q20k0hgjh0000gn/T/codex-clipboard-80c61501-238e-498f-bf92-f674995cde2a.png` (user-provided defect capture) plus Tailkit `a-c-chat-09` as the intended spacious card-header pattern.
- Browser-rendered implementation: `/var/folders/8j/qs8k8y3n1hlfbl4q20k0hgjh0000gn/T/tingting-header-fixed-mobile.png` and `/var/folders/8j/qs8k8y3n1hlfbl4q20k0hgjh0000gn/T/tingting-header-fixed-tablet.png`.
- Focused side-by-side comparison: `/var/folders/8j/qs8k8y3n1hlfbl4q20k0hgjh0000gn/T/tingting-header-comparison.png`.
- Viewports: 390 × 844 mobile detail and 768 × 900 split-pane tablet.
- State: authenticated Zalo OA conversation detail with chatbot ownership, candidate context action, and transcript scrolled to the latest messages.

### Full-view comparison evidence

- Mobile: the conversation detail remains 390px wide with no horizontal overflow. The transcript and takeover footer remain visible and independently scrollable.
- Tablet: the 316px directory and 334px conversation pane remain aligned inside the workspace frame with no overflow or clipped persistent controls.

### Focused header comparison evidence

- Before: candidate name wrapped, the raw provider ID split across multiple lines, and four actions competed with identity in one row.
- After: the candidate name stays on one line in a dedicated identity row; the provider ID is omitted in the constrained state; actions occupy a separate right-aligned toolbar row with 44px touch targets.

### Required fidelity surfaces

- Fonts and typography: Be Vietnam Pro is preserved; the contact name is readable at its existing weight without wrapping or forced character-level breaks.
- Spacing and layout rhythm: the narrow header uses two deliberate rows with an 8px gap and a hairline separator instead of compressing identity and controls.
- Colors and visual tokens: the existing Tailkit/Vantai white, zinc, hairline, and emerald action tokens are unchanged.
- Image quality and assets: existing source avatars and Lucide/product icons are preserved; no placeholder or replacement asset was introduced.
- Copy and content: Vietnamese labels and ARIA names are unchanged; only the low-value raw provider ID is hidden in the constrained header while remaining available on wider panes.

### Comparison history

1. P1 — cramped narrow-pane identity header. The user capture showed multiline name/ID wrapping and controls crowding the contact identity.
2. Fix — added a container-query two-row header for panes at or below 420px; identity owns the first row and actions own the second.
3. Post-fix evidence — mobile header is 378px wide with a 304px identity slot; tablet header is 334px wide with a 304px identity slot; both report no horizontal overflow.

### Interaction and console checks

- Authenticated navigation and Zalo OA conversation selection rendered successfully.
- List/detail responsive transition and persistent transcript/footer layout were exercised.
- No new console error was emitted during the corrected-header capture.

### Findings

- No remaining P0/P1/P2 mismatch in the corrected narrow header.
- P3: the extra toolbar row consumes additional vertical space, an intentional tradeoff to preserve readable identity and accessible action targets.

final result: passed
