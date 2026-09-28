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
          // Recursive capture is ON by default, which makes a group swallow its
          // matches' dependency closure too. That is wrong here: `ra-core`
          // peer-depends on `@tanstack/react-query`, `react-router` and
          // `react-hook-form` and imports all three, so the first group
          // (alphabetically declared before them) pulled 146 kB of other
          // vendors into `ra-vendor` and left `tanstack-vendor` and
          // `router-vendor` with nothing to emit. `false` restores one-module-
          // to-one-rule assignment, which is what `manualChunks` did.
          includeDependenciesRecursively: false,
          groups: [
            // React core — stable, must be in its own early-loaded chunk
            {
              name: "react-vendor",
              test: /node_modules[\\/]react(-dom)?[\\/]/,
            },
            // react-admin headless framework
            { name: "ra-vendor", test: /node_modules[\\/]ra-core[\\/]/ },
            // TanStack Query family
            {
              name: "tanstack-vendor",
              test: /node_modules[\\/]@tanstack[\\/]/,
            },
            // Icon set (large barrel)
            {
              name: "lucide-vendor",
              test: /node_modules[\\/]lucide-react[\\/]/,
            },
            // Routing (react-router + the react-router-dom compat shim)
            { name: "router-vendor", test: /node_modules[\\/]react-router/ },
            // Realtime transport
            {
              name: "realtime-vendor",
              test: /node_modules[\\/]socket\.io-client[\\/]/,
            },
            // Forms (form state + file drop)
            {
              name: "forms-vendor",
              test: /node_modules[\\/](react-hook-form|react-dropzone)[\\/]/,
            },
            // Virtualized lists (inbox thread + dashboard candidate list)
            { name: "virtua-vendor", test: /node_modules[\\/]virtua[\\/]/ },
            // Schema validation (eager: InstallationBootstrap → runtime manifest)
            { name: "zod-vendor", test: /node_modules[\\/]zod[\\/]/ },
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
