// Normalized message store (Rocket.Chat pattern). Messages live in a per-
// conversation Map keyed by id, so:
//   - switching conversations A→B→A does NOT refetch A (the cache persists)
//   - dedup is O(1) by id (optimistic temps + server echoes merge naturally)
//   - a sorted-array cache is recomputed only when the Map actually changes
//
// This replaces the prior per-mount useState in useConversationRealtime, which
// wiped message state on every conversation switch and caused A→B→A refetches.

import { create } from "zustand";
import { useMemo } from "react";
import type {
  ConversationMessageState,
  ConversationMessageStatePort,
  ConversationMessageStore,
} from "../application/conversation-runtime";
import type { ConversationMessage as Message } from "../domain/conversation-message";
import { compareMessages } from "../messageOrdering";

const emptyConv = (): ConversationMessageState => ({
  byId: new Map(),
  sortedCache: EMPTY_MESSAGES,
  hasMore: false,
  isLoading: true,
  isLoadingMore: false,
  initialError: null,
  historyError: null,
});

const EMPTY_MESSAGES: Message[] = [];

const recomputeSorted = (byId: Map<string, Message>): Message[] => {
  if (byId.size === 0) return EMPTY_MESSAGES;
  return Array.from(byId.values()).sort(compareMessages);
};

export const useMessageStore = create<ConversationMessageStore>((set) => ({
  conversations: new Map(),
  pendingOptimistic: new Map(),

  reset: (convId) =>
    set((s) => {
      const conversations = new Map(s.conversations);
      conversations.set(convId, emptyConv());
      const pendingOptimistic = new Map(s.pendingOptimistic);
      pendingOptimistic.set(convId, new Set());
      return { conversations, pendingOptimistic };
    }),

  setMessages: (convId, messages, hasMore) =>
    set((s) => {
      const byId = new Map<string, Message>();
      for (const m of messages) byId.set(m.id, m);
      const conversations = new Map(s.conversations);
      conversations.set(convId, {
        byId,
        sortedCache: recomputeSorted(byId),
        hasMore,
        isLoading: false,
        isLoadingMore: false,
        initialError: null,
        historyError: null,
      });
      return { conversations };
    }),

  upsert: (convId, incoming) =>
    set((s) => {
      const cur = s.conversations.get(convId);
      const byId = new Map<string, Message>(cur?.byId ?? new Map());
      let changed = false;
      for (const m of incoming) {
        const existing = byId.get(m.id);
        if (existing === m) continue;
        byId.set(m.id, m);
        changed = true;
      }
      if (!changed) return s;
      const conversations = new Map(s.conversations);
      conversations.set(convId, {
        ...(cur ?? emptyConv()),
        byId,
        sortedCache: recomputeSorted(byId),
      });
      return { conversations };
    }),

  patch: (convId, msgId, patch) =>
    set((s) => {
      const cur = s.conversations.get(convId);
      if (!cur) return s;
      const existing = cur.byId.get(msgId);
      if (!existing) return s;
      const byId = new Map(cur.byId);
      byId.set(msgId, { ...existing, ...patch });
      const conversations = new Map(s.conversations);
      conversations.set(convId, {
        ...cur,
        byId,
        sortedCache: recomputeSorted(byId),
      });
      return { conversations };
    }),

  remove: (convId, msgId) =>
    set((s) => {
      const cur = s.conversations.get(convId);
      if (!cur || !cur.byId.has(msgId)) return s;
      const byId = new Map(cur.byId);
      byId.delete(msgId);
      const conversations = new Map(s.conversations);
      conversations.set(convId, {
        ...cur,
        byId,
        sortedCache: recomputeSorted(byId),
      });
      const pendingOptimistic = new Map(s.pendingOptimistic);
      const pending = pendingOptimistic.get(convId);
      if (pending) {
        const nextPending = new Set(pending);
        nextPending.delete(msgId);
        pendingOptimistic.set(convId, nextPending);
      }
      return { conversations, pendingOptimistic };
    }),

  addPendingOptimistic: (convId, msgId) =>
    set((s) => {
      const pendingOptimistic = new Map(s.pendingOptimistic);
      const cur = pendingOptimistic.get(convId) ?? new Set<string>();
      const next = new Set(cur);
      next.add(msgId);
      pendingOptimistic.set(convId, next);
      return { pendingOptimistic };
    }),

  setHasMore: (convId, value) =>
    set((s) => {
      const cur = s.conversations.get(convId);
      if (!cur || cur.hasMore === value) return s;
      const conversations = new Map(s.conversations);
      conversations.set(convId, { ...cur, hasMore: value });
      return { conversations };
    }),

  setLoading: (convId, value) =>
    set((s) => {
      const cur = s.conversations.get(convId);
      if (!cur || cur.isLoading === value) return s;
      const conversations = new Map(s.conversations);
      conversations.set(convId, { ...cur, isLoading: value });
      return { conversations };
    }),

  setLoadingMore: (convId, value) =>
    set((s) => {
      const cur = s.conversations.get(convId);
      if (!cur || cur.isLoadingMore === value) return s;
      const conversations = new Map(s.conversations);
      conversations.set(convId, { ...cur, isLoadingMore: value });
      return { conversations };
    }),

  setInitialError: (convId, value) =>
    set((s) => {
      const cur = s.conversations.get(convId);
      if (!cur || cur.initialError === value) return s;
      const conversations = new Map(s.conversations);
      conversations.set(convId, { ...cur, initialError: value });
      return { conversations };
    }),

  setHistoryError: (convId, value) =>
    set((s) => {
      const cur = s.conversations.get(convId);
      if (!cur || cur.historyError === value) return s;
      const conversations = new Map(s.conversations);
      conversations.set(convId, { ...cur, historyError: value });
      return { conversations };
    }),

  clear: (convId) =>
    set((s) => {
      if (!s.conversations.has(convId)) return s;
      const conversations = new Map(s.conversations);
      conversations.delete(convId);
      const pendingOptimistic = new Map(s.pendingOptimistic);
      pendingOptimistic.delete(convId);
      return { conversations, pendingOptimistic };
    }),
  resetAll: () =>
    set({ conversations: new Map(), pendingOptimistic: new Map() }),
}));

export const conversationMessageStatePort: ConversationMessageStatePort = {
  getState: useMessageStore.getState,
  subscribe: useMessageStore.subscribe,
};

// --- Selector hooks ---

/** Sorted messages for a conversation (oldest→newest). Identity-stable across
 * reads when the underlying set is unchanged. */
export const useConversationMessages = (convId: string | undefined): Message[] => {
  return useMessageStore((s) => {
    if (!convId) return EMPTY_MESSAGES;
    return s.conversations.get(convId)?.sortedCache ?? EMPTY_MESSAGES;
  });
};

/** All loading/pagination flags for a conversation. */
export const useConversationFlags = (convId: string | undefined) => {
  const isLoading = useMessageStore((s) => {
    if (!convId) return true;
    const c = s.conversations.get(convId);
    return c?.isLoading ?? true;
  });
  const isLoadingMore = useMessageStore((s) => {
    if (!convId) return false;
    return s.conversations.get(convId)?.isLoadingMore ?? false;
  });
  const hasMore = useMessageStore((s) => {
    if (!convId) return false;
    return s.conversations.get(convId)?.hasMore ?? false;
  });
  const initialError = useMessageStore((s) => {
    if (!convId) return null;
    return s.conversations.get(convId)?.initialError ?? null;
  });
  const historyError = useMessageStore((s) => {
    if (!convId) return null;
    return s.conversations.get(convId)?.historyError ?? null;
  });

  return useMemo(
    () => ({ isLoading, isLoadingMore, hasMore, initialError, historyError }),
    [hasMore, historyError, initialError, isLoading, isLoadingMore],
  );
};

/** The newest real (non-optimistic) message id for a conversation, or null.
 * Used as the gap-fill cursor on reconnect. Reads the store snapshot directly
 * (not a hook) — for use inside callbacks. */
export const getNewestRealMessageId = (convId: string): string | null => {
  const state = useMessageStore.getState();
  const conv = state.conversations.get(convId);
  if (!conv) return null;
  const pending = state.pendingOptimistic.get(convId);
  for (let i = conv.sortedCache.length - 1; i >= 0; i--) {
    const m = conv.sortedCache[i];
    if (!pending?.has(m.id)) return m.id;
  }
  return null;
};
