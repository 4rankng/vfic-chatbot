import path from "node:path";
import { defineConfig } from "vitest/config";
import { playwright } from "@vitest/browser-playwright";
import react from "@vitejs/plugin-react";

// One test project (https://vitest.dev/guide/projects.html):
//   - "app": React/DOM unit tests, run in a real browser (Playwright/Chromium).
// Run it with `npm run test:unit:app`.
export default defineConfig({
  test: {
    coverage: {
      provider: "v8",
      // Whole-feature coverage so the number matches what it claims to measure:
      // the full atomic-crm tree under a ratchet floor (never lower it), while
      // the three changed/high-risk hardening files keep their own strict 80%
      // gate below. Measured 2026-09-24: 68.7 stmts / 58.1 branches / 59.5
      // funcs / 70.9 lines — floors sit a few points under to absorb runner
      // variance; raise them as coverage grows.
      include: ["src/components/atomic-crm/**/*.{ts,tsx}"],
      exclude: ["**/*.test.*", "**/.omc/**"],
      reporter: ["text", "json-summary"],
      thresholds: {
        statements: 67,
        branches: 55,
        functions: 57,
        lines: 68,
        "src/components/atomic-crm/capabilities/kernel/index.tsx": {
          statements: 80,
          branches: 80,
          functions: 80,
          lines: 80,
        },
        "src/components/atomic-crm/integrations/presentation/SecretField.tsx": {
          statements: 80,
          branches: 80,
          functions: 80,
          lines: 80,
        },
        "src/components/atomic-crm/performance/PerformanceTrendChart.tsx": {
          statements: 80,
          branches: 80,
          functions: 80,
          lines: 80,
        },
      },
    },
    projects: [
      {
        plugins: [react()],
        optimizeDeps: {
          // Pre-bundle the message store's selector middleware: discovered
          // mid-run it forced an optimizer reload that failed the file being
          // imported (zustand itself arrives through the app graph, the
          // /middleware entry does not).
          //
          // React Aria is listed for the same reason plus a sharper one:
          // pre-bundled without them it resolved a SECOND copy of React and
          // every React Aria component threw "Cannot read properties of null
          // (reading 'useContext')" in this browser project. Bundling the React
          // Aria entry points together keeps one React across the graph.
          include: [
            "zustand/middleware",
            "react-aria-components",
            "react-aria",
            "react-stately",
          ],
          exclude: ["playwright", "playwright-core"],
        },
        resolve: {
          // Belt and braces for the same duplicate-React failure.
          dedupe: ["react", "react-dom"],
          preserveSymlinks: true,
          alias: {
            "@": path.resolve(import.meta.dirname, "./src"),
          },
        },
        test: {
          name: "app",
          globals: true,
          // Browser-mode tests render in real Chromium, and `make release-check`
          // runs this suite concurrently with two other CPU-heavy lanes (backend
          // pytest with coverage, the migration walk). At the 15s default a
          // render test starved by that load fails as a timeout -- observed on
          // 2026-09-29 in RecruitingCommandCenter.render.test.tsx, which took
          // 18.4s while all three lanes ran and passes in ~2s alone. The extra
          // headroom does not weaken an assertion; a genuine hang still fails.
          testTimeout: 30_000,
          hookTimeout: 30_000,
          browser: {
            headless: true,
            provider: playwright(),
            enabled: true,
            instances: [
              {
                browser: "chromium",
                ...(process.env.CI && {
                  launch: { channel: "chromium-headless-shell" },
                }),
              },
            ],
            commands: {
              // Uses Chrome DevTools Protocol to override the timezone at runtime,
              // since process.env.TZ has no effect in a real browser environment.
              async setTimezone({ context, page }, timezoneId: string) {
                const session = await context.newCDPSession(page);
                await session.send("Emulation.setTimezoneOverride", {
                  timezoneId,
                });
                await session.detach();
              },
            },
          },
          exclude: [
            "**/node_modules/**",
            "e2e/**/*.spec.{ts,tsx}",
            ".claude/**",
          ],
          server: {
            deps: {
              external: [/playwright/],
            },
          },
        },
      },
    ],
  },
});
