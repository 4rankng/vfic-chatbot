/**
 * QA-only harness for the Cloudfone transcripts mobile pass (2026-10-21).
 *
 * Mounts CloudfoneTranscriptsSection alone — no router, no auth — so a
 * headless Chromium at 390×844 can screenshot the surface with the two
 * admin API calls answered from fixtures via Playwright route mocks.
 * Not part of the app build; only referenced by
 * qa/cloudfone-mobile-harness.html and qa/cloudfone-mobile-shots.cjs.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import "@/index.css";
import { CloudfoneTranscriptsSection } from "@/components/atomic-crm/integrations/CloudfoneTranscriptsSection";

const root = document.getElementById("root");
if (!root) throw new Error("harness: #root missing");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <div className="workspace-frame-content mx-auto min-h-screen max-w-[420px] p-3">
        <CloudfoneTranscriptsSection onBack={() => {}} />
      </div>
    </QueryClientProvider>
  </StrictMode>,
);
