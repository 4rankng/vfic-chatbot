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
  INITIAL_CHAT_FIRST_ITEM_INDEX,
  firstItemIndexAfterPrepend,
} from "./chatScrollIndex";

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

// Owns the realtime subscription + paginated message state for a conversation.
// Extracted from ChatThread so the message-loading logic is reusable across any
// shell and unit-testable in isolation (independent of the Virtuoso/composer UI).
//
export const useConversationRealtime = (conversationId?: string) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [firstItemIndex, setFirstItemIndex] = useState(
    INITIAL_CHAT_FIRST_ITEM_INDEX,
  );
  const isFetchingRef = useRef(false);
  const activeConversationRef = useRef<string | undefined>(conversationId);
  const requestSeqRef = useRef(0);
  const loadMoreAbortRef = useRef<AbortController | null>(null);
  // Optimistic-send tracking (Rocket.Chat pattern): temp ids of in-flight
  // recruiter messages. On the realtime echo of a confirmed message we drop the
  // matching temp so the real (server-id'd) row replaces it without a flicker.
  const pendingOptimisticIdsRef = useRef<Set<string>>(new Set());
  // Mirror `messages` into a ref so loadMore can read the latest set
  // synchronously. A setMessages functional updater runs later (during render),
  // so it can't itself return the count of newly-prepended rows; the ref lets
  // loadMore compute that count against state that already reflects any realtime
  // INSERT that landed during its await.
  const messagesRef = useRef<Message[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // Per-conversation isolation guards (defense-in-depth):
  //   cancelled         — this mount's effect was cleaned up (React strictness / double-invokes)
  //   requestSeqRef     — stale-mount guard: monotonic counter, rejects callbacks from a prior
  //                       conversationId mount cycle (catches temporal identity drift)
  //   activeConversationRef — stale-entity guard: rejects callbacks whose conversationId no longer
  //                           matches the selected conversation (catches entity identity drift)
  useEffect(() => {
    const activeConversationId = conversationId;
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    activeConversationRef.current = activeConversationId;
    isFetchingRef.current = false;
    loadMoreAbortRef.current?.abort();
    loadMoreAbortRef.current = null;
    setMessages([]);
    setHasMore(false);
    setFirstItemIndex(INITIAL_CHAT_FIRST_ITEM_INDEX);
    setIsLoading(true);

    let cancelled = false;
    const initialFetchAbort = new AbortController();

    const fetchInitial = async () => {
      if (!activeConversationId) {
        if (!cancelled && requestSeqRef.current === requestSeq) {
          setIsLoading(false);
        }
        return;
      }

      try {
        const { messages: mapped, hasMore: apiHasMore } =
          await chatRepository.getConversationMessages(activeConversationId, {
            limit: CHAT_MESSAGES_PAGE_SIZE,
            signal: initialFetchAbort.signal,
          });
        // Stale-response guard: see invariant block above
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
        // Merge, don't replace: a realtime INSERT between subscribe() and this
        // resolve is already in state, and a blind setMessages(mapped) would
        // drop it (the fetch predates the insert). Union by id, fetched-first.
        setMessages((prev) => {
          const currentConversationMessages = keepConversationMessages(
            prev,
            activeConversationId,
          );
          if (currentConversationMessages.length === 0) return chronological;
          return mergeChronological(currentConversationMessages, chronological);
        });
        setHasMore(apiHasMore);
      } catch {
        if (
          !cancelled &&
          requestSeqRef.current === requestSeq &&
          activeConversationRef.current === activeConversationId
        ) {
          setMessages([]);
          setHasMore(false);
        }
      } finally {
        if (!cancelled && requestSeqRef.current === requestSeq) {
          setIsLoading(false);
        }
      }
    };

    void fetchInitial();

    if (!activeConversationId) {
      return () => {
        cancelled = true;
        initialFetchAbort.abort();
        loadMoreAbortRef.current?.abort();
        loadMoreAbortRef.current = null;
      };
    }

    let cleanup: (() => void) | undefined;
    try {
      cleanup = chatRepository.subscribeToMessages(
        activeConversationId,
        (latest) => {
          // Stale-response guard: see invariant block above
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
          // Drop optimistic temps for this conversation once the server echoes a
          // real (server-id'd) outbound recruiter message — the real row replaces
          // the temp without a flicker. Rocket.Chat reuses the client _id on the
          // server; our backend doesn't, so we sweep by timestamp + content.
          const pendingIds = pendingOptimisticIdsRef.current;
          if (pendingIds.size > 0) {
            const realContentSet = new Set(
              currentLatest
                .filter((m) => m.type === "outbound" && m.data?.recruiter_id)
                .map((m) => `${m.content}|${m.created_at}`),
            );
            if (realContentSet.size > 0) {
              setMessages((prev) => {
                const kept = prev.filter((m) => {
                  if (!pendingIds.has(m.id)) return true;
                  // Keep the temp only if no real echo matches its content+ts.
                  return !realContentSet.has(`${m.content}|${m.created_at}`);
                });
                if (kept.length !== prev.length) {
                  // Temps were replaced; clear them from tracking.
                  for (const id of pendingIds) {
                    const stillPresent = kept.some((m) => m.id === id);
                    if (!stillPresent) pendingIds.delete(id);
                  }
                }
                return mergeRealtimePage(
                  keepConversationMessages(kept, activeConversationId),
                  currentLatest,
                );
              });
              return;
            }
          }
          setMessages((prev) =>
            mergeRealtimePage(
              keepConversationMessages(prev, activeConversationId),
              currentLatest,
            ),
          );
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
  }, [conversationId]);

  // Reconnect gap-fill (Rocket.Chat useLoadMissedMessages pattern): on Socket.IO
  // disconnect→reconnect, fetch any messages the server emitted while offline.
  // Without this, messages sent during the disconnect window are silently lost
  // to the client until the conversation is reopened. Uses the newest REAL
  // (non-optimistic) message id as the cursor.
  useEffect(() => {
    if (!conversationId) return;
    const socket = getRealtimeSocket();
    let wasConnected = socket.connected;

    const onConnect = async () => {
      if (wasConnected) return; // only fire on reconnect, not initial connect
      wasConnected = true;
      // Find the newest real (non-temp) message id currently loaded.
      const realMessages = messagesRef.current.filter(
        (m) => !pendingOptimisticIdsRef.current.has(m.id),
      );
      if (realMessages.length === 0) return;
      const newest = realMessages[realMessages.length - 1];
      try {
        const missed = await chatRepository.getMessagesSince(
          conversationId,
          newest.id,
        );
        if (missed.length === 0) return;
        setMessages((prev) =>
          mergeChronological(
            keepConversationMessages(prev, conversationId),
            missed,
          ),
        );
      } catch {
        // Best-effort: if the gap-fill fetch fails, the user can pull-to-refresh
        // or reopen the conversation. Don't crash the realtime loop.
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
  }, [conversationId]);

  // Stable identity so the consumer's useCallback(handleStartReached) memo
  // holds across renders — without this the startReached handler is rebuilt
  // every keystroke and Virtuoso re-binds the scroll listener.
  const loadMore = useCallback(
    async (earliestId: string): Promise<number> => {
      if (isFetchingRef.current || !hasMore || !conversationId) {
        return 0;
      }
      const activeConversationId = conversationId;
      const requestSeq = requestSeqRef.current;
      const loadMoreAbort = new AbortController();
      loadMoreAbortRef.current?.abort();
      loadMoreAbortRef.current = loadMoreAbort;
      isFetchingRef.current = true;
      setIsLoadingMore(true);

      try {
        const { messages: loadedOlder, hasMore: apiHasMore } =
          await chatRepository.getConversationMessages(activeConversationId, {
            limit: CHAT_MESSAGES_PAGE_SIZE,
            beforeId: earliestId,
            signal: loadMoreAbort.signal,
          });
        // Stale-response guard: see invariant block above
        if (
          requestSeqRef.current !== requestSeq ||
          activeConversationRef.current !== activeConversationId
        ) {
          return 0;
        }
        const older = keepConversationMessages(loadedOlder, activeConversationId);
        setHasMore(apiHasMore);
        // Return the number of fetched messages that are genuinely new vs current
        // state — NOT older.length. subscribeToMessages unions the newest page on
        // every realtime event and can land during the await above, so some of
        // `older` may already be in state; mergeChronological dedups those. If we
        // returned older.length we would over-count the prepend and inflate
        // Virtuoso's firstItemIndex, shifting every visible row to the wrong message.
        const existingIds = new Set(messagesRef.current.map((m) => m.id));
        const added = older.reduce(
          (n, m) => n + (existingIds.has(m.id) ? 0 : 1),
          0,
        );
        if (added > 0) {
          setFirstItemIndex((i) => firstItemIndexAfterPrepend(i, added));
        }
        setMessages((prev) => mergeChronological(prev, older));
        return added;
      } catch {
        if (
          requestSeqRef.current !== requestSeq ||
          activeConversationRef.current !== activeConversationId
        ) {
          return 0;
        }
        // A failed load-more must not keep re-firing on every scroll-to-top
        // (hasMore stays true -> the backend gets spammed with failing
        // requests). Stop the loop; reopening the conversation retries.
        setHasMore(false);
        return 0;
      } finally {
        if (
          requestSeqRef.current === requestSeq &&
          activeConversationRef.current === activeConversationId
        ) {
          setIsLoadingMore(false);
          isFetchingRef.current = false;
          if (loadMoreAbortRef.current === loadMoreAbort) {
            loadMoreAbortRef.current = null;
          }
        }
      }
    },
    [hasMore, conversationId],
  );

  // Insert an optimistic temp message (Rocket.Chat pattern). Returns the temp id
  // so the caller can mark it failed on send error. The temp is auto-removed when
  // the realtime echo of the real message arrives (see subscribeToMessages above).
  const insertOptimistic = useCallback(
    (content: string, recruiterId: string): string => {
      if (!conversationId) return "";
      // Use a client-side UUID that won't collide with server ids.
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
      pendingOptimisticIdsRef.current.add(tempId);
      setMessages((prev) => mergeChronological(prev, [temp]));
      return tempId;
    },
    [conversationId],
  );

  // Mark an optimistic message as failed (keep it visible with a failed badge so
  // the user can retry), or remove it entirely. Used when sendHumanReply errors.
  const markOptimisticFailed = useCallback((tempId: string) => {
    pendingOptimisticIdsRef.current.delete(tempId);
    setMessages((prev) =>
      prev.map((m) =>
        m.id === tempId ? { ...m, delivery_status: "failed" as const } : m,
      ),
    );
  }, []);

  return {
    messages,
    isLoading,
    isLoadingMore,
    hasMore,
    firstItemIndex,
    loadMore,
    insertOptimistic,
    markOptimisticFailed,
  };
};
