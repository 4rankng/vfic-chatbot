// VFIC runtime configuration.
//
// Source precedence: window.__VFIC__ (injected into index.html at deploy time)
// overrides VITE_* build-time env (used for local dev). Required keys throw a
// clear error when missing so a misconfigured deploy fails loudly instead of
// silently 404-ing. The human-reply webhook is feature-gated: when absent it
// resolves to null and the composer disables itself with a toast.

type VficWindowConfig = {
  SUPABASE_URL?: string;
  SB_PUBLISHABLE_KEY?: string;
  HUMAN_REPLY_WEBHOOK?: string;
};

const getWindowConfig = (): VficWindowConfig => {
  if (typeof window === "undefined") return {};
  return (window as unknown as { __VFIC__?: VficWindowConfig }).__VFIC__ ?? {};
};

// Cast to a string map so undeclared VITE_* keys (e.g. VITE_HUMAN_REPLY_WEBHOOK)
// typecheck without forcing a vite-env.d.ts edit per key.
const env = import.meta.env as unknown as Record<string, string | undefined>;
const win = getWindowConfig();

const required = (value: string | undefined, key: string): string => {
  if (!value) {
    throw new Error(
      `VFIC config: required key "${key}" is missing. Set window.__VFIC__.${key} in index.html (deploy) or VITE_${key} (build).`,
    );
  }
  return value;
};

export const vficConfig = {
  /** Supabase project URL. Required — throws if absent. */
  get supabaseUrl(): string {
    return required(win.SUPABASE_URL ?? env.VITE_SUPABASE_URL, "SUPABASE_URL");
  },
  /** Supabase publishable (anon) key. Required — throws if absent. */
  get supabasePublishableKey(): string {
    return required(
      win.SB_PUBLISHABLE_KEY ?? env.VITE_SB_PUBLISHABLE_KEY,
      "SB_PUBLISHABLE_KEY",
    );
  },
  /** n8n human-reply webhook URL. Feature-gated — null when unconfigured. */
  get humanReplyWebhookUrl(): string | null {
    return win.HUMAN_REPLY_WEBHOOK ?? env.VITE_HUMAN_REPLY_WEBHOOK ?? null;
  },
} as const;
