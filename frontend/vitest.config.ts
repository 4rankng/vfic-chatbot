import path from "node:path";
import { defineConfig } from "vitest/config";
import { playwright } from "@vitest/browser-playwright";
import react from "@vitejs/plugin-react";

// Two test projects (https://vitest.dev/guide/projects.html):
//   - "app":    React/DOM unit tests, run in a real browser (Playwright/Chromium).
//   - "claude": agent-harness hook tests, plain Node integration tests that spawn
//               the .claude/hooks/*.mjs hooks as subprocesses. No DOM, no browser.
// Run everything with `npm run test:unit:app`, or a single suite with
// `npm run test:unit:claude` (neither boots a browser).
export default defineConfig({
  test: {
    coverage: {
      provider: "v8",
      // Enforced 80% gate for the changed/high-risk hardening surface only.
      // The whole app test suite still runs separately without weakening this
      // focused contract into a misleading whole-tree coverage claim.
      include: [
        "src/components/atomic-crm/capabilities/kernel/index.tsx",
        "src/components/atomic-crm/integrations/CredentialSecretField.tsx",
        "src/components/atomic-crm/performance/PerformanceTrendChart.tsx",
      ],
      exclude: ["**/*.test.*", "**/.omc/**"],
      reporter: ["text", "json-summary"],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80,
      },
    },
    projects: [
      {
        plugins: [react()],
        optimizeDeps: {
          exclude: ["playwright", "playwright-core"],
        },
        resolve: {
          preserveSymlinks: true,
          alias: {
            "@": path.resolve(__dirname, "./src"),
          },
        },
        test: {
          name: "app",
          globals: true,
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
            // Harness hook tests are Node-only (they import node:fs / node:path
            // and spawn subprocesses); they run under the "claude" project below.
            ".claude/**",
          ],
          server: {
            deps: {
              external: [/playwright/],
            },
          },
        },
      },
      {
        test: {
          name: "claude",
          environment: "node",
          include: [".claude/**/*.test.mjs"],
          // These tests spawn `node` subprocesses and do real git/worktree work,
          // so they need more headroom than the default 5s.
          testTimeout: 30000,
          hookTimeout: 30000,
        },
      },
    ],
  },
});
