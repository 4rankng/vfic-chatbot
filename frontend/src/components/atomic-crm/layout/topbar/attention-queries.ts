// One namespace for every needs-attention query in the workspace:
//
//   ["conversations", "needs-attention", <kind>]
//
// `<kind>` is always a literal discriminator ("counts" | "rows"); the channel
// provider is NEVER part of a key. The namespace used to be overloaded —
// element 2 was a channel provider in `ChannelAdapterSelector` and the literal
// "rows" in `useNeedsAttention` — so a provider-scoped count query and the
// popover's rows query could not be invalidated independently.

const ATTENTION_QUERY_PREFIX = ["conversations", "needs-attention"] as const;

/**
 * Refresh cadence shared by the attention queries. Polling replaced the four
 * independent 30s timers this family used to run; see `useAttentionCounts`
 * for why polling rather than socket invalidation.
 */
export const ATTENTION_REFRESH_INTERVAL_MS = 60_000;

/**
 * The single counts cache entry holding `{total, byProvider}` that the topbar
 * bell and the inbox adapter selector share (see `useAttentionCounts`).
 */
export const ATTENTION_COUNTS_QUERY_KEY = [
  ...ATTENTION_QUERY_PREFIX,
  "counts",
] as const;

/**
 * The popover's recent-row page. Distinct `kind` so it can never collide with,
 * or be served from, the counts entry.
 */
export const ATTENTION_ROWS_QUERY_KEY = [
  ...ATTENTION_QUERY_PREFIX,
  "rows",
] as const;
