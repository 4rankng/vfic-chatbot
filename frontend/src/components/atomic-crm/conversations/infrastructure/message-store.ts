// Normalized message store (Rocket.Chat pattern). Messages live in a per-
// conversation Map keyed by id, so:
//   - switching conversations A→B→A does NOT refetch A (the cache persists)
//   - dedup is O(1) by id (optimistic temps + server echoes merge naturally)
//   - a sorted-array cache is recomputed only when the Map actually changes
//
// The cache is bounded: `touchConversation` is called when a conversation is
// opened, moves it to the front of the LRU order and `clear`s the entries past
// MAX_CACHED_CONVERSATIONS, so a long shift of conversation switching cannot
// grow the tab's message memory forever.
//
// This replaces the prior per-mount useState in useConversationRealtime, which
// wiped message state on every conversation switch and caused A→B→A refetches.

import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import type {
  ConversationMessageState,
  ConversationMessageStatePort,
  ConversationMessageStore,
} from "../application/conversation-runtime";
import type { ConversationMessage as Message } from "../domain/conversation-message";
import { compareMessages } from "../messageOrdering";

/** Conversations whose message state stays cached. Switching past this bound
 * evicts the least recently used conversation. */
export const MAX_CACHED_CONVERSATIONS = 5;

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

export const useMessageStore = create<ConversationMessageStore>()(
  subscribeWithSelector((set, get) => ({
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

    touchConversation: (convId) => {
      // Recency order is the `conversations` Map insertion order. A conversation
      // opened for the first time is appended by reset/setMessages, so it is
      // already the most recently used entry; an already cached one is moved
      // there explicitly.
      const cached = get().conversations;
      if (cached.has(convId) && Array.from(cached.keys()).at(-1) !== convId) {
        set((s) => {
          const conversations = new Map(s.conversations);
          const entry = conversations.get(convId);
          if (!entry) return s;
          conversations.delete(convId);
          conversations.set(convId, entry);
          return { conversations };
        });
      }

      const current = get().conversations;
      if (current.size <= MAX_CACHED_CONVERSATIONS) return;
      // Oldest entries first. `convId` is skipped, so the conversation being
      // opened — including its in-flight optimistic messages — is never a
      // victim of its own eviction pass.
      const victims = Array.from(current.keys())
        .filter((id) => id !== convId)
        .slice(0, current.size - MAX_CACHED_CONVERSATIONS);
      for (const id of victims) get().clear(id);
    },

    resetAll: () =>
      set({ conversations: new Map(), pendingOptimistic: new Map() }),
  })),
);

export const conversationMessageStatePort: ConversationMessageStatePort = {
  getState: useMessageStore.getState,
  subscribeTo: (selector, listener) =>
    useMessageStore.subscribe(selector, listener),
};
