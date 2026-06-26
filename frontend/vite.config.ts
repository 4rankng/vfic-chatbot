import path from "node:path";
import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";
import createHtmlPlugin from "vite-plugin-simple-html";
import { VitePWA } from "vite-plugin-pwa";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    visualizer({
      open: process.env.NODE_ENV !== "CI",
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
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024, // 5 MiB
      },
      manifest: false, // Use existing manifest.json from public/
    }),
  ],
  base: "./",
  esbuild: {
    keepNames: true,
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          // React core — stable, must be in its own early-loaded chunk
          if (id.includes("/react-dom/") || id.includes("/react/")) {
            return "react-vendor";
          }
          // react-admin headless framework
          if (id.includes("/ra-core/") || id.includes("/ra-supabase")) {
            return "ra-vendor";
          }
          // TanStack Query family
          if (id.includes("/@tanstack/")) {
            return "tanstack-vendor";
          }
          // Supabase JS client
          if (id.includes("/@supabase/")) {
            return "supabase-vendor";
          }
          // Icon set (large barrel)
          if (id.includes("/lucide-react/")) {
            return "lucide-vendor";
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
