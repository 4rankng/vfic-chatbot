import { useCallback, useEffect, useRef, useState } from "react";
import type { Message } from "../types";
import { chatRepository } from "./chatRepository";

// Owns the realtime subscription + paginated message state for a conversation.
// Extracted from ChatThread so the message-loading logic is reusable across any
// shell and unit-testable in isolation (independent of the Virtuoso/composer UI).
//
// Merge semantics matter: a realtime INSERT that lands between subscribe() and
// the initial fetch resolve is already in state, so the fetch result is merged
// (union by id, fetched-first) rather than blindly replacing state.
export const useConversationRealtime = (conversationId?: string) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const isFetchingRef = useRef(false);

  const fetchInitial = async () => {
    if (!conversationId) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      const { messages: mapped, hasMore: apiHasMore } =
        await chatRepository.getConversationMessages(conversationId, {
          limit: 10,
        });
      // Merge, don't replace: a realtime INSERT between subscribe() and this
      // resolve is already in state, and a blind setMessages(mapped) would
      // drop it (the fetch predates the insert). Union by id, fetched-first.
      setMessages((prev) => {
        if (prev.length === 0) return mapped;
        const fetchedIds = new Set(mapped.map((m) => m.id));
        const realtimeOnly = prev.filter((m) => !fetchedIds.has(m.id));
        return realtimeOnly.length > 0 ? [...mapped, ...realtimeOnly] : mapped;
      });
      setHasMore(apiHasMore);
    } catch {
      setMessages([]);
      setHasMore(false);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    setMessages([]);
    setHasMore(false);
    fetchInitial();

    if (!conversationId) return;

    let cleanup: (() => void) | undefined;
    try {
      cleanup = chatRepository.subscribeToMessages(conversationId, (newMsg) => {
        setMessages((prev) =>
          prev.some((m) => m.id === newMsg.id) ? prev : [...prev, newMsg],
        );
      });
    } catch {}

    return () => {
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
      isFetchingRef.current = true;
      setIsLoadingMore(true);

      try {
        const { messages: older, hasMore: apiHasMore } =
          await chatRepository.getConversationMessages(conversationId, {
            limit: 10,
            beforeId: earliestId,
          });
        setHasMore(apiHasMore);
        setMessages((prev) => [...older, ...prev]);
        return older.length;
      } catch {
        // A failed load-more must not keep re-firing on every scroll-to-top
        // (hasMore stays true -> the backend gets spammed with failing
        // requests). Stop the loop; reopening the conversation retries.
        setHasMore(false);
        return 0;
      } finally {
        setIsLoadingMore(false);
        isFetchingRef.current = false;
      }
    },
    [hasMore, conversationId],
  );

  return { messages, isLoading, isLoadingMore, hasMore, loadMore };
};
