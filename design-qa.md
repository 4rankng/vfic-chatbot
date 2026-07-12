# Design QA — Performance Dashboard

## Reference

Selected design direction: diagnostic matrix (Image Gen option 2), based on the
existing `/hieu-suat` screen and the light Ting Ting workspace system.

## Verification

- Typecheck: passed.
- Lint: passed.
- Production build: passed.
- Authenticated local route: rendered successfully with the admin session.
- Window control: verified `24 giờ` → `1 giờ`; the selected state and copy
  updated correctly.
- Refresh: renders a loading state and refreshed timestamp.
- Empty window: verified the calm, explanatory state for missing trend,
  percentile, and slow-turn data.
- Mobile: verified at 390 × 844; header, two-column metric grid, loading state,
  and bottom navigation remain inside the viewport with no horizontal scroll.
- Populated local data: verified the p95 target line, error buckets, attention
  queue, candidate/internal latency matrix, delivery summary, lane mix, and a
  20-row slow-turn list with expanded LLM, DB/tool, token, and trace detail.

## Result

final result: passed

## Required Follow-up

The local seed now includes healthy, warning, and failure telemetry for future
performance-page reviews.
