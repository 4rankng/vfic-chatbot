// VFIC runtime configuration.
//
// The CRM talks to a self-hosted REST + SSE backend (FastAPI). Source
// precedence: window.__VFIC__ (injected into index.html at deploy time)
// overrides VITE_* build-time env (used for local dev). `apiBaseUrl` is the
// backend origin (empty = same-origin); `realtimeUrl` is the SSE endpoint and
// defaults to <apiBaseUrl>/realtime/events.

type VficWindowConfig = {
  API_BASE?: string;
  REALTIME_URL?: string;
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
  /** Legacy n8n human-reply webhook — optional, superseded by the REST endpoint. */
  get humanReplyWebhookUrl(): string | null {
    return win.HUMAN_REPLY_WEBHOOK ?? env.VITE_HUMAN_REPLY_WEBHOOK ?? null;
  },
} as const;
