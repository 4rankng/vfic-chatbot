// Owns the realtime subscription + paginated fetching for a conversation.
// Message STATE lives in the normalized messageStore (Zustand Map<id,msg>),
// which persists across conversation switches — eliminating the A→B→A refetch
// problem the prior per-mount useState had. This hook is now purely about
// *driving data into the store* (initial fetch, load-more, realtime subscribe,
// reconnect gap-fill, optimistic insert), not holding arrays.
//
// Rocket.Chat pattern: store = Map<id, msg>, sorted array derived at the
// selector boundary, optimistic temps tracked for sweep-on-echo. The cache is
// LRU-bounded: opening a conversation evicts the least recently used one past
// MAX_CACHED_CONVERSATIONS (see touchConversation in the store).

import { useCallback, useEffect, useRef, useState } from "react";
import type { Message } from "../../types";
import {
  getConversationMessageRepository,
  getConversationMessageState,
} from "../application/conversation-runtime";
import {
  findConfirmedOptimisticIds,
  isOptimisticMessageId,
  keepConversationMessages,
} from "../domain/conversation-thread";
import {
  mergeChronological,
  mergeRealtimePage,
  sortMessagesChronologically,
} from "../messageOrdering";
import {
  useConversationFlags,
  useConversationMessages,
} from "./conversation-message-state";

export {
  compareMessages,
  mergeChronological,
  mergeRealtimePage,
} from "../messageOrdering";

export const CHAT_MESSAGES_PAGE_SIZE = 20;
const findConfirmedOptimisticIdsInStore = (
  conversationId: string,
  confirmedMessages: Message[],
) => {
  const state = getConversationMessageState().getState();
  const pending = state.pendingOptimistic.get(conversationId);
  const conv = state.conversations.get(conversationId);
  if (!pending || pending.size === 0 || !conv) return [];

  return findConfirmedOptimisticIds({
    confirmedMessages,
    pendingMessages: Array.from(pending)
      .map((tempId) => conv.byId.get(tempId))
      .filter((message): message is Message => Boolean(message)),
  });
};

export const useConversationRealtime = (conversationId?: string) => {
  // Drive the store from this hook. The store holds the actual state.
  const {
    reset: resetMessages,
    setMessages,
    upsert: upsertMessages,
    remove: removeMessage,
    addPendingOptimistic,
    patch: patchMessage,
    setHasMore,
    setLoadingMore,
    setInitialError,
    setHistoryError,
    touchConversation,
  } = getConversationMessageState().getState();
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
    // the conversation has no cached messages yet — which is also the case when
    // the conversation was evicted by the cache bound.
    const existing = getConversationMessageState()
      .getState()
      .conversations.get(activeConversationId);
    if (!existing || existing.byId.size === 0) {
      resetMessages(activeConversationId);
    }

    // Bound the store: mark this conversation most recently used and evict the
    // least recently used conversations past MAX_CACHED_CONVERSATIONS. Runs
    // after the reset above so a freshly opened conversation is in the cache
    // (and therefore in the recency order) before the bound is enforced; the
    // active conversation is never a victim, so its in-flight optimistic
    // messages survive the pass.
    touchConversation(activeConversationId);

    let cancelled = false;
    const initialFetchAbort = new AbortController();

    const fetchInitial = async () => {
      try {
        const { messages: mapped, hasMore: apiHasMore } =
          await getConversationMessageRepository().getConversationMessages(
            activeConversationId,
            {
              limit: CHAT_MESSAGES_PAGE_SIZE,
              signal: initialFetchAbort.signal,
            },
          );
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
        for (const tempId of findConfirmedOptimisticIdsInStore(
          activeConversationId,
          chronological,
        )) {
          removeMessage(activeConversationId, tempId);
        }
        // setMessages replaces the conversation's set entirely (initial load).
        // Any realtime insert that landed during the await is unioned in by
        // merging against the current store snapshot first.
        const current = getConversationMessageState()
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
          const current = getConversationMessageState()
            .getState()
            .conversations.get(activeConversationId);
          if (current) {
            getConversationMessageState()
              .getState()
              .setLoading(activeConversationId, false);
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
      cleanup = getConversationMessageRepository().subscribeToMessages(
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
          for (const tempId of findConfirmedOptimisticIdsInStore(
            activeConversationId,
            currentLatest,
          )) {
            removeMessage(activeConversationId, tempId);
          }

          // Merge only messages in the loaded window (drop older-than-earliest).
          const conv = getConversationMessageState()
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
      requestSeqRef.current += 1;
      if (activeConversationRef.current === activeConversationId) {
        activeConversationRef.current = undefined;
      }
      isFetchingRef.current = false;
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
    touchConversation,
    upsertMessages,
    initialRetry,
  ]);

  // Reconnect gap-fill (Rocket.Chat useLoadMissedMessages pattern): on Socket.IO
  // disconnect→reconnect, fetch any messages the server emitted while offline.
  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    let wasConnected = getConversationMessageRepository().isConnected();

    const onConnect = async () => {
      if (wasConnected) return;
      wasConnected = true;
      // Newest real (non-temp) message id is the cursor.
      const conv = getConversationMessageState()
        .getState()
        .conversations.get(conversationId);
      if (!conv || conv.byId.size === 0) return;
      let newestId: string | null = null;
      const pending = getConversationMessageState()
        .getState()
        .pendingOptimistic.get(conversationId);
      for (let i = conv.sortedCache.length - 1; i >= 0; i--) {
        const m = conv.sortedCache[i];
        if (!pending?.has(m.id) && !isOptimisticMessageId(m.id)) {
          newestId = m.id;
          break;
        }
      }
      if (!newestId) return;
      try {
        let cursor = newestId;
        while (!cancelled) {
          const { messages: page, hasMore } =
            await getConversationMessageRepository().getMessagesSince(
              conversationId,
              cursor,
            );
          if (cancelled || page.length === 0) break;
          for (const tempId of findConfirmedOptimisticIdsInStore(
            conversationId,
            page,
          )) {
            removeMessage(conversationId, tempId);
          }
          upsertMessages(conversationId, page);
          const nextCursor = page[page.length - 1]?.id;
          if (!nextCursor || nextCursor === cursor || !hasMore) break;
          cursor = nextCursor;
        }
      } catch {
        // Best-effort: pages already fetched remain committed, and a later
        // reconnect resumes from the newest committed message id.
      }
    };
    const onDisconnect = () => {
      wasConnected = false;
    };

    const unsubscribe =
      getConversationMessageRepository().subscribeToConnection(
        onConnect,
        onDisconnect,
      );
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [conversationId, removeMessage, upsertMessages]);

  // Load-more (scroll up for older history). With virtua's `shift` prop handling
  // scroll anchoring, we no longer track firstItemIndex — just fetch + upsert.
  const loadMore = useCallback(
    async (earliestId: string): Promise<void> => {
      if (isFetchingRef.current || !conversationId) return;
      const state = getConversationMessageState().getState();
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
          await getConversationMessageRepository().getConversationMessages(
            activeConversationId,
            {
              limit: CHAT_MESSAGES_PAGE_SIZE,
              beforeId: earliestId,
              signal: loadMoreAbort.signal,
            },
          );
        if (
          requestSeqRef.current !== requestSeq ||
          activeConversationRef.current !== activeConversationId
        ) {
          return;
        }
        const older = keepConversationMessages(
          loadedOlder,
          activeConversationId,
        );
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
            error instanceof Error
              ? error.message
              : "Không tải được tin nhắn cũ.",
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
    [
      conversationId,
      setHasMore,
      setHistoryError,
      setLoadingMore,
      upsertMessages,
    ],
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

  // Mark an optimistic message as failed (keep visible with failed badge). It
  // deliberately remains eligible for reconciliation: an HTTP failure can be
  // returned after the server has already persisted and broadcast the message.
  const markOptimisticFailed = useCallback(
    (tempId: string) => {
      if (!conversationId) return;
      patchMessage(conversationId, tempId, { delivery_status: "failed" });
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
