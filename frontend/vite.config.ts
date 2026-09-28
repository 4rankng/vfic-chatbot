import path from "node:path";
import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";
import createHtmlPlugin from "vite-plugin-simple-html";
import { VitePWA } from "vite-plugin-pwa";

// https://vitejs.dev/config/

// Dev backend port — tracks `make dev`'s BACKEND_PORT (default 8000) so the
// dev-server proxy below stays in sync when the port is overridden to dodge
// collisions with other local stacks. Read at config-eval time (Node), not
// client-side, so it does not need the VITE_ prefix.
const backendPort = process.env.BACKEND_PORT ?? "8000";
const backendUrl = `http://localhost:${backendPort}`;
const analyzeBundle = process.env.ANALYZE === "true";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    analyzeBundle &&
      visualizer({
        open: true,
        filename: "./dist/stats.html",
      }),
    createHtmlPlugin({
      minify: true,
      inject: {
        data: {
          mainScript: `src/main.tsx`,
        },
      },
    }),
    VitePWA({
      registerType: "autoUpdate",
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff,woff2}"],
        globIgnores: [
          "**/appIcon/**",
          "**/favicon*.{ico,png}",
          "**/preview.png",
          "**/*logo*.png",
          "**/login-*",
          "**/*recruit*",
          "**/zalo_verifier*.html",
          "**/auth-callback.html",
        ],
        // Backend-owned paths must bypass the service worker's navigation
        // fallback. Without this denylist the SW serves the cached SPA shell
        // for top-level navigations to /api/* (mode: "navigate"), so Facebook's
        // OAuth redirect never reaches the backend callback endpoint.
        navigateFallbackDenylist: [
          /^\/api\//,
          /^\/webhooks\//,
          /^\/realtime\//,
          /^\/socket\.io\//,
        ],
        cleanupOutdatedCaches: true,
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024, // 5 MiB
      },
      manifest: false, // Use existing manifest.json from public/
    }),
  ],
  base: "./",
  // Dev-server dependency optimizer. Lazy route modules pull deep CJS entries
  // (the `lodash/*` per-function files, `react-dropzone`, `cmdk`) that Vite only
  // discovers when the route first renders. Each discovery re-bundles the
  // optimizer and invalidates every dep URL the running page already holds —
  // "504 (Outdated Optimize Dep)" followed by "Failed to fetch dynamically
  // imported module" and a React error boundary, which is what made the console
  // unusable in dev after the Vite 8 toolchain change reset the optimizer cache.
  // Declaring the app's external imports up front lets one optimize pass cover
  // them, so navigating never triggers a re-bundle. Builds are unaffected.
  optimizeDeps: {
    include: [
      "@radix-ui/react-accordion",
      "@radix-ui/react-avatar",
      "@radix-ui/react-checkbox",
      "@radix-ui/react-dialog",
      "@radix-ui/react-dropdown-menu",
      "@radix-ui/react-label",
      "@radix-ui/react-popover",
      "@radix-ui/react-progress",
      "@radix-ui/react-radio-group",
      "@radix-ui/react-select",
      "@radix-ui/react-separator",
      "@radix-ui/react-slot",
      "@radix-ui/react-tabs",
      "@radix-ui/react-toggle",
      "@radix-ui/react-toggle-group",
      "@radix-ui/react-tooltip",
      "@tanstack/react-query",
      "@untitledui/icons",
      "class-variance-authority",
      "clsx",
      "cmdk",
      "dompurify",
      "inflection",
      "input-otp",
      "lodash/get",
      "lodash/isEqual",
      "lodash/matches",
      "lodash/pickBy",
      "lucide-react",
      "marked",
      "query-string",
      "ra-core",
      "ra-i18n-polyglot",
      "react-aria",
      "react-aria-components",
      "react-dropzone",
      "react-error-boundary",
      "react-hook-form",
      "react-router",
      "react-router-dom",
      "react-stately",
      "socket.io-client",
      "sonner",
      "tailwind-merge",
      "virtua",
      "zod",
      "zustand",
      "zustand/middleware",
    ],
  },
  // Dev server: proxy backend endpoints to uvicorn so the SPA stays same-origin
  // (apiBaseUrl="") in local dev — no VITE_API_BASE or CORS needed. Covers REST
  // (/api), SSE (/realtime) and Socket.IO (WebSocket upgrade). The target tracks
  // backendUrl (= BACKEND_PORT) so `make dev BACKEND_PORT=8001` stays in sync.
  server: {
    proxy: {
      "/api": backendUrl,
      "/realtime": backendUrl,
      "/socket.io": { target: backendUrl, ws: true },
    },
  },
  build: {
    sourcemap: true,
    // Vite 8 bundles with Rolldown, so `rollupOptions` is renamed and the
    // minifier is oxc. `manualChunks` is replaced by `codeSplitting.groups`;
    // the deprecated `manualChunks` object form is not supported at all and the
    // function form is ignored when `codeSplitting` is present.
    rolldownOptions: {
      output: {
        // Replaces the Vite 7 top-level `esbuild.keepNames`. oxc owns
        // minification now, so the flag has to sit on the Rolldown output where
        // the minifier runs. Function and class `name` values survive — stack
        // traces stay readable instead of collapsing to single letters.
        keepNames: true,
        // Vendor chunk rules below are keyed by package path, so they MUST
        // track the actual imports: a rule for a package nothing imports spends
        // a split on dead weight, and a heavy package on the hot path with no
        // rule silently lands in whichever chunk imports it first.
        //
        // Each `test` is anchored on the `/node_modules/<pkg>/` path segment:
        // `react` must not swallow `react-aria`, `react-hook-form`,
        // `react-router` or `@tanstack/react-query`, which carry their own
        // rules below. `[\\/]` matches either path separator.
        codeSplitting: {
          // Recursive capture stays ON (the default). Disabling it was the
          // mistake that shipped a broken bundle: Rolldown documents that
          // `includeDependenciesRecursively: false` can generate chunks with
          // invalid execution order unless it is paired with
          // `preserveEntrySignatures: false | 'allow-extension'` and
          // `strictExecutionOrder: true`, and the built bundle died at boot with
          // `TypeError: D is not a function` while the dev server was fine.
          //
          // The reason it was disabled still has to be solved, and `priority`
          // solves it: `ra-core` peer-depends on `@tanstack/react-query`,
          // `react-router` and `react-hook-form` and imports all three, so with
          // equal priority the first group captured their modules and
          // `tanstack-vendor`/`router-vendor` emitted nothing. Groups with a
          // higher priority are matched first and their modules are removed from
          // later groups, so the three specific rules below win before
          // `ra-vendor`'s closure can take them.
          includeDependenciesRecursively: true,
          groups: [
            // These three first: `ra-core` imports all of them, so they must be
            // claimed before `ra-vendor` (priority 0) is considered.
            {
              name: "tanstack-vendor",
              test: /node_modules[\\/]@tanstack[\\/]/,
              priority: 30,
            },
            {
              name: "router-vendor",
              test: /node_modules[\\/]react-router/,
              priority: 30,
            },
            {
              name: "forms-vendor",
              test: /node_modules[\\/](react-hook-form|react-dropzone)[\\/]/,
              priority: 30,
            },
            // React core — stable, must be in its own early-loaded chunk
            {
              name: "react-vendor",
              test: /node_modules[\\/]react(-dom)?[\\/]/,
              priority: 20,
            },
            // Icon set (large barrel)
            {
              name: "lucide-vendor",
              test: /node_modules[\\/]lucide-react[\\/]/,
              priority: 10,
            },
            // Realtime transport
            {
              name: "realtime-vendor",
              test: /node_modules[\\/]socket\.io-client[\\/]/,
              priority: 10,
            },
            // Virtualized lists (inbox thread + dashboard candidate list)
            {
              name: "virtua-vendor",
              test: /node_modules[\\/]virtua[\\/]/,
              priority: 10,
            },
            // Schema validation (eager: InstallationBootstrap → runtime manifest)
            {
              name: "zod-vendor",
              test: /node_modules[\\/]zod[\\/]/,
              priority: 10,
            },
            // react-admin headless framework — last, so its dependency closure
            // (date-fns, lodash, query-string, …) only takes what the rules
            // above did not claim.
            {
              name: "ra-vendor",
              test: /node_modules[\\/]ra-core[\\/]/,
              priority: 0,
            },
          ],
        },
      },
    },
  },
  resolve: {
    preserveSymlinks: true,
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
});
