// Owns the realtime subscription + paginated fetching for a conversation.
// Message STATE lives in the normalized messageStore (Zustand Map<id,msg>),
// which persists across conversation switches — eliminating the A→B→A refetch
// problem the prior per-mount useState had. This hook is now purely about
// *driving data into the store* (initial fetch, load-more, realtime subscribe,
// reconnect gap-fill, optimistic insert), not holding arrays.
//
// Rocket.Chat pattern: store = Map<id, msg>, sorted array derived at the
// selector boundary, optimistic temps tracked for sweep-on-echo.

import { useCallback, useEffect, useRef, useState } from "react";
import type { Message } from "../types";
import { chatRepository } from "./chatRepository";
import { getRealtimeSocket } from "@/lib/vfic/realtimeSocket";
import {
  mergeChronological,
  mergeRealtimePage,
  sortMessagesChronologically,
} from "./messageOrdering";
import {
  useConversationFlags,
  useConversationMessages,
  useMessageStore,
} from "./messageStore";

export {
  compareMessages,
  mergeChronological,
  mergeRealtimePage,
} from "./messageOrdering";

export const CHAT_MESSAGES_PAGE_SIZE = 20;
const OPTIMISTIC_ID_PREFIX = "optimistic-";
const OPTIMISTIC_CONFIRM_WINDOW_MS = 5 * 60 * 1000;

const keepConversationMessages = (
  messages: Message[],
  conversationId: string,
) => messages.filter((message) => message.conversation_id === conversationId);

const parseMessageTime = (message: Message) => {
  const value = Date.parse(message.created_at);
  return Number.isFinite(value) ? value : null;
};

const isConfirmedHumanReply = (message: Message) =>
  message.type === "outbound" &&
  Boolean(message.data?.recruiter_id) &&
  !message.id.startsWith(OPTIMISTIC_ID_PREFIX);

const findConfirmedOptimisticIds = (
  conversationId: string,
  confirmedMessages: Message[],
) => {
  const state = useMessageStore.getState();
  const pending = state.pendingOptimistic.get(conversationId);
  const conv = state.conversations.get(conversationId);
  if (!pending || pending.size === 0 || !conv) return [];

  const matchedTempIds = new Set<string>();
  for (const confirmed of confirmedMessages.filter(isConfirmedHumanReply)) {
    const confirmedAt = parseMessageTime(confirmed);
    let bestMatch: { delta: number; id: string } | null = null;

    for (const tempId of pending) {
      if (matchedTempIds.has(tempId)) continue;
      const temp = conv.byId.get(tempId);
      if (!temp || temp.delivery_status === "failed") continue;
      if (temp.content !== confirmed.content) continue;
      if (temp.type !== confirmed.type) continue;
      if (temp.data?.recruiter_id !== confirmed.data?.recruiter_id) continue;

      const tempAt = parseMessageTime(temp);
      const delta =
        confirmedAt != null && tempAt != null
          ? Math.abs(confirmedAt - tempAt)
          : 0;
      if (delta > OPTIMISTIC_CONFIRM_WINDOW_MS) continue;
      if (!bestMatch || delta < bestMatch.delta) {
        bestMatch = { delta, id: tempId };
      }
    }

    if (bestMatch) {
      matchedTempIds.add(bestMatch.id);
    }
  }

  return Array.from(matchedTempIds);
};

export const useConversationRealtime = (conversationId?: string) => {
  // Drive the store from this hook. The store holds the actual state.
  const resetMessages = useMessageStore((s) => s.reset);
  const setMessages = useMessageStore((s) => s.setMessages);
  const upsertMessages = useMessageStore((s) => s.upsert);
  const removeMessage = useMessageStore((s) => s.remove);
  const addPendingOptimistic = useMessageStore((s) => s.addPendingOptimistic);
  const patchMessage = useMessageStore((s) => s.patch);
  const setHasMore = useMessageStore((s) => s.setHasMore);
  const setLoadingMore = useMessageStore((s) => s.setLoadingMore);
  const setInitialError = useMessageStore((s) => s.setInitialError);
  const setHistoryError = useMessageStore((s) => s.setHistoryError);
  const messages = useConversationMessages(conversationId);
  const flags = useConversationFlags(conversationId);
  const isFetchingRef = useRef(false);
  const activeConversationRef = useRef<string | undefined>(conversationId);
  const requestSeqRef = useRef(0);
  const loadMoreAbortRef = useRef<AbortController | null>(null);
  const [initialRetry, setInitialRetry] = useState(0);

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

    setInitialError(activeConversationId, null);

    // Reset the conversation's store state on open. If messages are already
    // cached (e.g. returning from A→B→A), setMessages below will refresh them;
    // but we mark loading so the UI shows a spinner briefly only if the cache
    // is empty. To avoid wiping a warm cache on rapid switches, only reset when
    // the conversation has no cached messages yet.
    const existing = useMessageStore
      .getState()
      .conversations.get(activeConversationId);
    if (!existing || existing.byId.size === 0) {
      resetMessages(activeConversationId);
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
        for (const tempId of findConfirmedOptimisticIds(
          activeConversationId,
          chronological,
        )) {
          removeMessage(activeConversationId, tempId);
        }
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
        setMessages(activeConversationId, merged, apiHasMore);
      } catch (error: unknown) {
        if (
          !cancelled &&
          requestSeqRef.current === requestSeq &&
          activeConversationRef.current === activeConversationId
        ) {
          const current = useMessageStore
            .getState()
            .conversations.get(activeConversationId);
          if (current) {
            useMessageStore.getState().setLoading(activeConversationId, false);
          }
          setInitialError(
            activeConversationId,
            error instanceof Error ? error.message : "Không tải được tin nhắn.",
          );
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

          // Sweep optimistic temps confirmed by real server echoes. The backend
          // creates its own ids/timestamps, so pair by sender + content within a
          // tight send window instead of requiring timestamp equality.
          for (const tempId of findConfirmedOptimisticIds(
            activeConversationId,
            currentLatest,
          )) {
            removeMessage(activeConversationId, tempId);
          }

          // Merge only messages in the loaded window (drop older-than-earliest).
          const conv = useMessageStore
            .getState()
            .conversations.get(activeConversationId);
          const currentArr = conv ? Array.from(conv.byId.values()) : [];
          const inWindow = mergeRealtimePage(currentArr, currentLatest);
          upsertMessages(activeConversationId, inWindow);
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
  }, [
    conversationId,
    removeMessage,
    resetMessages,
    setMessages,
    setInitialError,
    upsertMessages,
    initialRetry,
  ]);

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
        for (const tempId of findConfirmedOptimisticIds(conversationId, missed)) {
          removeMessage(conversationId, tempId);
        }
        upsertMessages(conversationId, missed);
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
  }, [conversationId, removeMessage, upsertMessages]);

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
      setLoadingMore(activeConversationId, true);

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
        setHasMore(activeConversationId, apiHasMore);
        setHistoryError(activeConversationId, null);
        if (older.length > 0) {
          upsertMessages(activeConversationId, older);
        }
      } catch (error: unknown) {
        if (
          requestSeqRef.current === requestSeq &&
          activeConversationRef.current === activeConversationId
        ) {
          setHistoryError(
            activeConversationId,
            error instanceof Error ? error.message : "Không tải được tin nhắn cũ.",
          );
        }
      } finally {
        if (
          requestSeqRef.current === requestSeq &&
          activeConversationRef.current === activeConversationId
        ) {
          setLoadingMore(activeConversationId, false);
          isFetchingRef.current = false;
          if (loadMoreAbortRef.current === loadMoreAbort) {
            loadMoreAbortRef.current = null;
          }
        }
      }
    },
    [conversationId, setHasMore, setHistoryError, setLoadingMore, upsertMessages],
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
      addPendingOptimistic(conversationId, tempId);
      upsertMessages(conversationId, [temp]);
      return tempId;
    },
    [addPendingOptimistic, conversationId, upsertMessages],
  );

  // Mark an optimistic message as failed (keep visible with failed badge).
  const markOptimisticFailed = useCallback(
    (tempId: string) => {
      if (!conversationId) return;
      patchMessage(conversationId, tempId, { delivery_status: "failed" });
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
    [conversationId, patchMessage],
  );

  return {
    messages,
    ...flags,
    loadMore,
    insertOptimistic,
    markOptimisticFailed,
    retryInitial: () => setInitialRetry((value) => value + 1),
    retryHistory: (earliestId: string) => loadMore(earliestId),
  };
};
