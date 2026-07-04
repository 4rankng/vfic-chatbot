// Owns the realtime subscription + paginated fetching for a conversation.
// Message STATE lives in the normalized messageStore (Zustand Map<id,msg>),
// which persists across conversation switches — eliminating the A→B→A refetch
// problem the prior per-mount useState had. This hook is now purely about
// *driving data into the store* (initial fetch, load-more, realtime subscribe,
// reconnect gap-fill, optimistic insert), not holding arrays.
//
// Rocket.Chat pattern: store = Map<id, msg>, sorted array derived at the
// selector boundary, optimistic temps tracked for sweep-on-echo.

import { useCallback, useEffect, useRef } from "react";
import type { Message } from "../types";
import { chatRepository } from "./chatRepository";
import { getRealtimeSocket } from "@/lib/vfic/realtimeSocket";
import {
  mergeChronological,
  mergeRealtimePage,
  sortMessagesChronologically,
} from "./messageOrdering";
import { useMessageStore } from "./messageStore";

export {
  compareMessages,
  mergeChronological,
  mergeRealtimePage,
} from "./messageOrdering";

export const CHAT_MESSAGES_PAGE_SIZE = 10;

const keepConversationMessages = (
  messages: Message[],
  conversationId: string,
) => messages.filter((message) => message.conversation_id === conversationId);

export const useConversationRealtime = (conversationId?: string) => {
  // Drive the store from this hook. The store holds the actual state.
  const store = useMessageStore();
  const isFetchingRef = useRef(false);
  const activeConversationRef = useRef<string | undefined>(conversationId);
  const requestSeqRef = useRef(0);
  const loadMoreAbortRef = useRef<AbortController | null>(null);

  // Initial fetch + subscribe on conversation open/switch.
  useEffect(() => {
    const activeConversationId = conversationId;
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    activeConversationRef.current = activeConversationId;
    isFetchingRef.current = false;
    loadMoreAbortRef.current?.abort();
    loadMoreAbortRef.current = null;

    if (!activeConversationId) {
      return;
    }

    // Reset the conversation's store state on open. If messages are already
    // cached (e.g. returning from A→B→A), setMessages below will refresh them;
    // but we mark loading so the UI shows a spinner briefly only if the cache
    // is empty. To avoid wiping a warm cache on rapid switches, only reset when
    // the conversation has no cached messages yet.
    const existing = store.conversations.get(activeConversationId);
    if (!existing || existing.byId.size === 0) {
      store.reset(activeConversationId);
    }

    let cancelled = false;
    const initialFetchAbort = new AbortController();

    const fetchInitial = async () => {
      try {
        const { messages: mapped, hasMore: apiHasMore } =
          await chatRepository.getConversationMessages(activeConversationId, {
            limit: CHAT_MESSAGES_PAGE_SIZE,
            signal: initialFetchAbort.signal,
          });
        if (
          cancelled ||
          requestSeqRef.current !== requestSeq ||
          activeConversationRef.current !== activeConversationId
        ) {
          return;
        }
        const chronological = keepConversationMessages(
          sortMessagesChronologically(mapped),
          activeConversationId,
        );
        // setMessages replaces the conversation's set entirely (initial load).
        // Any realtime insert that landed during the await is unioned in by
        // merging against the current store snapshot first.
        const current = useMessageStore
          .getState()
          .conversations.get(activeConversationId);
        const merged =
          current && current.byId.size > 0
            ? mergeChronological(
                Array.from(current.byId.values()),
                chronological,
              )
            : chronological;
        store.setMessages(activeConversationId, merged, apiHasMore);
      } catch {
        if (
          !cancelled &&
          requestSeqRef.current === requestSeq &&
          activeConversationRef.current === activeConversationId
        ) {
          store.setMessages(activeConversationId, [], false);
        }
      }
    };

    void fetchInitial();

    let cleanup: (() => void) | undefined;
    try {
      cleanup = chatRepository.subscribeToMessages(
        activeConversationId,
        (latest) => {
          if (
            cancelled ||
            requestSeqRef.current !== requestSeq ||
            activeConversationRef.current !== activeConversationId
          ) {
            return;
          }
          const currentLatest = keepConversationMessages(
            latest,
            activeConversationId,
          );
          if (currentLatest.length === 0) return;

          // Sweep optimistic temps whose content+ts matches a real echo, then
          // upsert the real page. Rocket.Chat reuses the client _id on confirm;
          // our backend doesn't, so we sweep by content+timestamp.
          const state = useMessageStore.getState();
          const pending = state.pendingOptimistic.get(activeConversationId);
          if (pending && pending.size > 0) {
            const realContentSet = new Set(
              currentLatest
                .filter((m) => m.type === "outbound" && m.data?.recruiter_id)
                .map((m) => `${m.content}|${m.created_at}`),
            );
            if (realContentSet.size > 0) {
              for (const tempId of pending) {
                const tempMsg = state.conversations
                  .get(activeConversationId)
                  ?.byId.get(tempId);
                if (
                  tempMsg &&
                  realContentSet.has(`${tempMsg.content}|${tempMsg.created_at}`)
                ) {
                  store.remove(activeConversationId, tempId);
                }
              }
            }
          }

          // Merge only messages in the loaded window (drop older-than-earliest).
          const conv = useMessageStore
            .getState()
            .conversations.get(activeConversationId);
          const currentArr = conv ? Array.from(conv.byId.values()) : [];
          const inWindow = mergeRealtimePage(currentArr, currentLatest);
          store.upsert(activeConversationId, inWindow);
        },
      );
    } catch {
      // Realtime is best-effort; the initial REST fetch still renders history.
    }

    return () => {
      cancelled = true;
      initialFetchAbort.abort();
      loadMoreAbortRef.current?.abort();
      loadMoreAbortRef.current = null;
      cleanup?.();
    };
  }, [conversationId, store]);

  // Reconnect gap-fill (Rocket.Chat useLoadMissedMessages pattern): on Socket.IO
  // disconnect→reconnect, fetch any messages the server emitted while offline.
  useEffect(() => {
    if (!conversationId) return;
    const socket = getRealtimeSocket();
    let wasConnected = socket.connected;

    const onConnect = async () => {
      if (wasConnected) return;
      wasConnected = true;
      // Newest real (non-temp) message id is the cursor.
      const conv = useMessageStore.getState().conversations.get(conversationId);
      if (!conv || conv.byId.size === 0) return;
      let newestId: string | null = null;
      const pending = useMessageStore
        .getState()
        .pendingOptimistic.get(conversationId);
      for (let i = conv.sortedCache.length - 1; i >= 0; i--) {
        const m = conv.sortedCache[i];
        if (!pending?.has(m.id)) {
          newestId = m.id;
          break;
        }
      }
      if (!newestId) return;
      try {
        const missed = await chatRepository.getMessagesSince(
          conversationId,
          newestId,
        );
        if (missed.length === 0) return;
        store.upsert(conversationId, missed);
      } catch {
        // Best-effort gap-fill.
      }
    };
    const onDisconnect = () => {
      wasConnected = false;
    };

    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    return () => {
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
    };
  }, [conversationId, store]);

  // Load-more (scroll up for older history). With virtua's `shift` prop handling
  // scroll anchoring, we no longer track firstItemIndex — just fetch + upsert.
  const loadMore = useCallback(
    async (earliestId: string): Promise<void> => {
      if (isFetchingRef.current || !conversationId) return;
      const state = useMessageStore.getState();
      const conv = state.conversations.get(conversationId);
      if (!conv || !conv.hasMore) return;

      const activeConversationId = conversationId;
      const requestSeq = requestSeqRef.current;
      const loadMoreAbort = new AbortController();
      loadMoreAbortRef.current?.abort();
      loadMoreAbortRef.current = loadMoreAbort;
      isFetchingRef.current = true;
      store.setLoadingMore(activeConversationId, true);

      try {
        const { messages: loadedOlder, hasMore: apiHasMore } =
          await chatRepository.getConversationMessages(activeConversationId, {
            limit: CHAT_MESSAGES_PAGE_SIZE,
            beforeId: earliestId,
            signal: loadMoreAbort.signal,
          });
        if (
          requestSeqRef.current !== requestSeq ||
          activeConversationRef.current !== activeConversationId
        ) {
          return;
        }
        const older = keepConversationMessages(loadedOlder, activeConversationId);
        store.setHasMore(activeConversationId, apiHasMore);
        if (older.length > 0) {
          store.upsert(activeConversationId, older);
        }
      } catch {
        if (
          requestSeqRef.current === requestSeq ||
          activeConversationRef.current === activeConversationId
        ) {
          store.setHasMore(activeConversationId, false);
        }
      } finally {
        if (
          requestSeqRef.current === requestSeq &&
          activeConversationRef.current === activeConversationId
        ) {
          store.setLoadingMore(activeConversationId, false);
          isFetchingRef.current = false;
          if (loadMoreAbortRef.current === loadMoreAbort) {
            loadMoreAbortRef.current = null;
          }
        }
      }
    },
    [conversationId, store],
  );

  // Insert an optimistic temp message. Returns the temp id.
  const insertOptimistic = useCallback(
    (content: string, recruiterId: string): string => {
      if (!conversationId) return "";
      const tempId = `optimistic-${crypto.randomUUID()}`;
      const now = new Date().toISOString();
      const temp: Message = {
        id: tempId,
        zalo_message_id: "",
        conversation_id: conversationId,
        type: "outbound",
        content,
        delivery_status: "pending",
        data: { recruiter_id: recruiterId },
        created_at: now,
      };
      store.addPendingOptimistic(conversationId, tempId);
      store.upsert(conversationId, [temp]);
      return tempId;
    },
    [conversationId, store],
  );

  // Mark an optimistic message as failed (keep visible with failed badge).
  const markOptimisticFailed = useCallback(
    (tempId: string) => {
      if (!conversationId) return;
      store.patch(conversationId, tempId, { delivery_status: "failed" });
      // No longer pending (it's now a failed real-visible row).
      const pending = useMessageStore
        .getState()
        .pendingOptimistic.get(conversationId);
      if (pending?.has(tempId)) {
        const next = new Set(pending);
        next.delete(tempId);
        useMessageStore.setState((s) => {
          const m = new Map(s.pendingOptimistic);
          m.set(conversationId, next);
          return { pendingOptimistic: m };
        });
      }
    },
    [conversationId, store],
  );

  return {
    loadMore,
    insertOptimistic,
    markOptimisticFailed,
  };
};
