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

final result: blocked
