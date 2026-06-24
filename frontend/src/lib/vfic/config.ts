// VFIC runtime configuration.
//
// After the FastAPI cutover the CRM talks to a self-hosted REST + SSE backend.
// Source precedence: window.__VFIC__ (injected into index.html at deploy time)
// overrides VITE_* build-time env (used for local dev). `apiBaseUrl` is the
// backend origin (empty = same-origin); `realtimeUrl` is the SSE endpoint and
// defaults to <apiBaseUrl>/realtime/events. The legacy Supabase keys are kept
// as optional for any transitional tooling but are no longer required by the
// CRM data layer.

type VficWindowConfig = {
  API_BASE?: string;
  REALTIME_URL?: string;
  // Legacy (Supabase era) — optional, unused by the REST data layer.
  SUPABASE_URL?: string;
  SB_PUBLISHABLE_KEY?: string;
  HUMAN_REPLY_WEBHOOK?: string;
};

const getWindowConfig = (): VficWindowConfig => {
  if (typeof window === "undefined") return {};
  return (window as unknown as { __VFIC__?: VficWindowConfig }).__VFIC__ ?? {};
};

// Cast to a string map so undeclared VITE_* keys typecheck without forcing a
// vite-env.d.ts edit per key.
const env = import.meta.env as unknown as Record<string, string | undefined>;
const win = getWindowConfig();

const trailing = (value: string): string => value.replace(/\/+$/, "");

export const vficConfig = {
  /** Backend origin (no trailing slash). Empty = same-origin (Caddy co-served). */
  get apiBaseUrl(): string {
    return trailing(win.API_BASE ?? env.VITE_API_BASE ?? "");
  },
  /** SSE endpoint for realtime events. Defaults to <apiBaseUrl>/realtime/events. */
  get realtimeUrl(): string {
    return (
      win.REALTIME_URL ??
      env.VITE_REALTIME_URL ??
      `${this.apiBaseUrl}/realtime/events`
    );
  },
  /** Legacy Supabase project URL — optional, retained for transitional tooling. */
  get supabaseUrl(): string | null {
    return win.SUPABASE_URL ?? env.VITE_SUPABASE_URL ?? null;
  },
  /** Legacy Supabase publishable key — optional, retained for transitional tooling. */
  get supabasePublishableKey(): string | null {
    return win.SB_PUBLISHABLE_KEY ?? env.VITE_SB_PUBLISHABLE_KEY ?? null;
  },
  /** Legacy n8n human-reply webhook — optional, superseded by the REST endpoint. */
  get humanReplyWebhookUrl(): string | null {
    return win.HUMAN_REPLY_WEBHOOK ?? env.VITE_HUMAN_REPLY_WEBHOOK ?? null;
  },
} as const;
