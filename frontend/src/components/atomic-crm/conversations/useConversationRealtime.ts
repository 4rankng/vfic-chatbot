import { useCallback, useEffect, useRef, useState } from "react";
import type { Message } from "../types";
import { chatRepository } from "./chatRepository";
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

  return {
    messages,
    isLoading,
    isLoadingMore,
    hasMore,
    firstItemIndex,
    loadMore,
  };
};
