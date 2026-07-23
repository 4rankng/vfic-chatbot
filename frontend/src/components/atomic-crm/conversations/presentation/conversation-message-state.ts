import { useSyncExternalStore } from "react";

import { getConversationMessageState } from "../application/conversation-runtime";
import type { ConversationMessage } from "../domain/conversation-message";

const EMPTY_MESSAGES: ConversationMessage[] = [];

const useMessageStateSelector = <T,>(selector: () => T): T => {
  const statePort = getConversationMessageState();
  return useSyncExternalStore(statePort.subscribe, selector, selector);
};

export const useConversationMessages = (
  conversationId: string | undefined,
): ConversationMessage[] =>
  useMessageStateSelector(() => {
    if (!conversationId) return EMPTY_MESSAGES;
    return (
      getConversationMessageState()
        .getState()
        .conversations.get(conversationId)?.sortedCache ?? EMPTY_MESSAGES
    );
  });

export const useConversationFlags = (
  conversationId: string | undefined,
) => {
  const isLoading = useMessageStateSelector(() => {
    if (!conversationId) return true;
    return (
      getConversationMessageState()
        .getState()
        .conversations.get(conversationId)?.isLoading ?? true
    );
  });
  const isLoadingMore = useMessageStateSelector(() => {
    if (!conversationId) return false;
    return (
      getConversationMessageState()
        .getState()
        .conversations.get(conversationId)?.isLoadingMore ?? false
    );
  });
  const hasMore = useMessageStateSelector(() => {
    if (!conversationId) return false;
    return (
      getConversationMessageState()
        .getState()
        .conversations.get(conversationId)?.hasMore ?? false
    );
  });
  const initialError = useMessageStateSelector(() => {
    if (!conversationId) return null;
    return (
      getConversationMessageState()
        .getState()
        .conversations.get(conversationId)?.initialError ?? null
    );
  });
  const historyError = useMessageStateSelector(() => {
    if (!conversationId) return null;
    return (
      getConversationMessageState()
        .getState()
        .conversations.get(conversationId)?.historyError ?? null
    );
  });
  return { isLoading, isLoadingMore, hasMore, initialError, historyError };
};
