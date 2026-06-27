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
const compareMessages = (a: Message, b: Message) => {
  const at = Date.parse(a.created_at);
  const bt = Date.parse(b.created_at);
  if (Number.isFinite(at) && Number.isFinite(bt) && at !== bt) return at - bt;
  const aid = Number(a.id);
  const bid = Number(b.id);
  if (Number.isFinite(aid) && Number.isFinite(bid) && aid !== bid)
    return aid - bid;
  return String(a.id).localeCompare(String(b.id));
};

const mergeChronological = (current: Message[], incoming: Message[]) => {
  const byId = new Map<string, Message>();
  for (const msg of current) byId.set(msg.id, msg);
  for (const msg of incoming) byId.set(msg.id, msg);
  return Array.from(byId.values()).sort(compareMessages);
};

export const useConversationRealtime = (conversationId?: string) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const isFetchingRef = useRef(false);
  // Mirror `messages` into a ref so loadMore can read the latest set
  // synchronously. A setMessages functional updater runs later (during render),
  // so it can't itself return the count of newly-prepended rows; the ref lets
  // loadMore compute that count against state that already reflects any realtime
  // INSERT that landed during its await.
  const messagesRef = useRef<Message[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const fetchInitial = useCallback(async () => {
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
        return mergeChronological(prev, mapped);
      });
      setHasMore(apiHasMore);
    } catch {
      setMessages([]);
      setHasMore(false);
    } finally {
      setIsLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    setMessages([]);
    setHasMore(false);
    fetchInitial();

    if (!conversationId) return;

    let cleanup: (() => void) | undefined;
    try {
      cleanup = chatRepository.subscribeToMessages(conversationId, (newMsg) => {
        setMessages((prev) => mergeChronological(prev, [newMsg]));
      });
    } catch {
      // Realtime is best-effort; the initial REST fetch still renders history.
    }

    return () => {
      cleanup?.();
    };
  }, [conversationId, fetchInitial]);

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
        setMessages((prev) => mergeChronological(prev, older));
        return added;
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
