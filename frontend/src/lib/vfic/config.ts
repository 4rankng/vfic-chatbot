// VFIC runtime configuration.
//
// The CRM talks to a self-hosted REST + Socket.IO backend (FastAPI). Source
// precedence: window.__VFIC__ (injected into index.html at deploy time)
// overrides VITE_* build-time env (used for local dev). `apiBaseUrl` is the
// backend origin (empty = same-origin); `socketUrl` is the Socket.IO origin.

type VficWindowConfig = {
  API_BASE?: string;
  SOCKET_URL?: string;
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
  /**
   * Socket.IO origin for realtime chat. Defaults to the backend origin
   * (apiBaseUrl; empty = same-origin, co-served by Caddy); the socket path is
   * the server default /socket.io/. Socket.IO prefers WebSocket and falls back
   * to HTTP long-polling automatically.
   */
  get socketUrl(): string {
    return win.SOCKET_URL ?? env.VITE_SOCKET_URL ?? this.apiBaseUrl;
  },
} as const;
