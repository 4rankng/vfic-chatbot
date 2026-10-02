# Performance page redesign (Hiệu suất chatbot)

Date: 2026-10-02 · Branch: main · Scope: `/hieu-suat` admin dashboard, frontend + backend metrics

## Outcome

Redesigned the performance dashboard around a derived health verdict, using the
installed Untitled UI PRO layer, and extended the backend payload with the
window-quality metrics the page now displays.

- **Verdict band (new focal surface):** one strip answers "is the bot OK" —
  Ổn định / Cần chú ý / Sự cố, derived from the same signal rules the attention
  queue lists, plus the p95-vs-10s promise (p50 alongside). Shared signal
  collection lives in `presentation/signals.ts` so band and queue cannot
  disagree.
- **Live tiles:** queue, worker saturation (with Untitled UI `ProgressBarBase`
  meter), LLM 429, delivery checks, success rate (new), turns processed.
- **Chart:** tone-coloured bars against the 10-second target line with a target
  pill, left-edge seconds scale, and a React hover tooltip per bucket; the
  sr-only data table now clips in the feature sheet (stays hidden where
  Tailwind's `sr-only` is not emitted, e.g. the browser-test harness).
- **Windows:** attention queue with tone-chipped icons; slow-turn table with
  quiet severity dots instead of double badges; SupportingStats gained
  "Chất lượng xử lý" (degraded/429/cache-hit/tokens) and "Dữ liệu & đồng bộ"
  (trend coverage + external-source sync counters, previously computed but
  never displayed).
- **Backend:** `performance_dashboard` gained a concurrent `_quality` read
  (degraded incl. legacy throttle key, retried-429, prompt-cache hit rate,
  prompt/completion/cached token sums) exposed as `quality` on
  `GET /admin/performance`. Nine concurrent reads on the 10-pool, docstring
  updated.
- All icons on the page moved from lucide to `@untitledui/icons`; header lost
  the uppercase kicker; refresh is the library Button; daisyUI `tt-table`/
  `tt-card` classes removed from the page.

## Verification

- Frontend: typecheck clean; 33/33 tests in `performance/` (states, page,
  trend-layers, trendAxis); css-scoping, untitledui-theme-contract and
  ui-design-dependency suites 11/11; eslint + prettier clean on touched files;
  generated-component reachability unchanged.
- Visual: rendered with rich mock data at 1280px and 390px via a scratch
  vitest-browser `toMatchScreenshot` harness (deleted after review); verdict
  band, tiles, chart target/scale/tones and mobile stacking confirmed.
- Backend: `tests/test_performance_endpoint.py` 11/11 (route fakes extended,
  quality assertions added, concurrency test updated for the ninth read).

## Commits

- `2b2b5de7` backend quality aggregates
- `ed92fd41` page redesign (committed by the parallel session from this tree)
- `a386f6d3` quality types, sr-table clip, test-fixture hygiene

## Notes / open items

- `docs/architecture/api.md` is dirty in the parallel session's working tree;
  the `quality` response fields should be added there once their edit lands.
- Stale `__screenshots__/performance-trend-layers.test.tsx/*.png` baselines in
  git depict the old design; no test references them — safe to delete in a
  later cleanup.
- Pool headroom note: the dashboard now opens nine concurrent sessions per
  uncached request against `pool_size=10`; acceptable for an admin view, worth
  revisiting if more reads are added.
