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
      // Enforced 80% gate for the changed/high-risk hardening surface only.
      // The whole app test suite still runs separately without weakening this
      // focused contract into a misleading whole-tree coverage claim.
      include: [
        "src/components/atomic-crm/capabilities/kernel/index.tsx",
        "src/components/atomic-crm/integrations/presentation/SecretField.tsx",
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
          // Pre-bundle the message store's selector middleware: discovered
          // mid-run it forced an optimizer reload that failed the file being
          // imported (zustand itself arrives through the app graph, the
          // /middleware entry does not).
          include: ["zustand/middleware"],
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
          exclude: ["**/node_modules/**", "e2e/**/*.spec.{ts,tsx}", ".claude/**"],
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
