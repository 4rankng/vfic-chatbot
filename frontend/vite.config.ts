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
  esbuild: {
    keepNames: true,
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        // Vendor chunk rules below are keyed by package path, so they MUST
        // track the actual imports: a rule for a package nothing imports spends
        // a split on dead weight, and a heavy package on the hot path with no
        // rule silently lands in whichever chunk imports it first.
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          // React core — stable, must be in its own early-loaded chunk
          if (id.includes("/react-dom/") || id.includes("/react/")) {
            return "react-vendor";
          }
          // react-admin headless framework
          if (id.includes("/ra-core/")) {
            return "ra-vendor";
          }
          // TanStack Query family
          if (id.includes("/@tanstack/")) {
            return "tanstack-vendor";
          }
          // Icon set (large barrel)
          if (id.includes("/lucide-react/")) {
            return "lucide-vendor";
          }
          // Routing (react-router + the react-router-dom compat shim)
          if (id.includes("/react-router")) {
            return "router-vendor";
          }
          // Realtime transport
          if (id.includes("/socket.io-client/")) {
            return "realtime-vendor";
          }
          // Forms (form state + file drop)
          if (
            id.includes("/react-hook-form/") ||
            id.includes("/react-dropzone/")
          ) {
            return "forms-vendor";
          }
          // Virtualized lists (inbox thread + dashboard candidate list)
          if (id.includes("/virtua/")) {
            return "virtua-vendor";
          }
          // Schema validation (eager: InstallationBootstrap → runtime manifest)
          if (id.includes("/zod/")) {
            return "zod-vendor";
          }
        },
      },
    },
  },
  resolve: {
    preserveSymlinks: true,
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
