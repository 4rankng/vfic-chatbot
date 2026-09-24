// Store-backed selector hooks for one conversation's messages and flags.
// Selection happens inside the store subscription (`subscribeTo`), so a store
// write for conversation A never notifies conversation B's subscribers.

import { useCallback, useSyncExternalStore } from "react";

import { getConversationMessageState } from "../application/conversation-runtime";
import type {
  ConversationMessageState,
  ConversationMessageStore,
} from "../application/conversation-runtime";
import type { ConversationMessage } from "../domain/conversation-message";

const EMPTY_MESSAGES: ConversationMessage[] = [];

const useMessageStateSelector = <T>(
  select: (state: ConversationMessageStore) => T,
): T => {
  const statePort = getConversationMessageState();
  const subscribe = useCallback(
    (onStoreChange: () => void) => statePort.subscribeTo(select, onStoreChange),
    [select, statePort],
  );
  const getSnapshot = useCallback(
    () => select(statePort.getState()),
    [select, statePort],
  );
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
};

type ConversationFlags = Omit<ConversationMessageState, "byId" | "sortedCache">;

/** One flag of one conversation. Absent conversation (never loaded, or evicted
 * from the cache) reads as the flag's "nothing loaded yet" value. */
const useConversationFlag = <K extends keyof ConversationFlags>(
  conversationId: string | undefined,
  field: K,
  fallback: ConversationFlags[K],
): ConversationFlags[K] =>
  useMessageStateSelector(
    useCallback(
      (state: ConversationMessageStore) =>
        (conversationId
          ? state.conversations.get(conversationId)?.[field]
          : undefined) ?? fallback,
      [conversationId, field, fallback],
    ),
  );

export const useConversationMessages = (
  conversationId: string | undefined,
): ConversationMessage[] =>
  useMessageStateSelector(
    useCallback(
      (state: ConversationMessageStore) =>
        conversationId
          ? (state.conversations.get(conversationId)?.sortedCache ??
            EMPTY_MESSAGES)
          : EMPTY_MESSAGES,
      [conversationId],
    ),
  );

export const useConversationFlags = (conversationId: string | undefined) => ({
  isLoading: useConversationFlag(conversationId, "isLoading", true),
  isLoadingMore: useConversationFlag(conversationId, "isLoadingMore", false),
  hasMore: useConversationFlag(conversationId, "hasMore", false),
  initialError: useConversationFlag(conversationId, "initialError", null),
  historyError: useConversationFlag(conversationId, "historyError", null),
});
