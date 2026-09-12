import type {
  ConversationMessageRepository,
  ConversationSummary,
} from "./ports";
import type { ConversationMessage } from "../domain/conversation-message";

export type ConversationMessageState = {
  byId: Map<string, ConversationMessage>;
  sortedCache: ConversationMessage[];
  hasMore: boolean;
  isLoading: boolean;
  isLoadingMore: boolean;
  initialError: string | null;
  historyError: string | null;
};

export type ConversationMessageStore = {
  conversations: Map<string, ConversationMessageState>;
  pendingOptimistic: Map<string, Set<string>>;
  reset(convId: string): void;
  setMessages(
    convId: string,
    messages: ConversationMessage[],
    hasMore: boolean,
  ): void;
  upsert(convId: string, incoming: ConversationMessage[]): void;
  patch(
    convId: string,
    msgId: string,
    patch: Partial<ConversationMessage>,
  ): void;
  remove(convId: string, msgId: string): void;
  addPendingOptimistic(convId: string, msgId: string): void;
  setHasMore(convId: string, value: boolean): void;
  setLoading(convId: string, value: boolean): void;
  setLoadingMore(convId: string, value: boolean): void;
  setInitialError(convId: string, value: string | null): void;
  setHistoryError(convId: string, value: string | null): void;
  clear(convId: string): void;
  resetAll(): void;
};

export interface ConversationMessageStatePort {
  getState(): ConversationMessageStore;
  subscribe(listener: () => void): () => void;
}

let repository: ConversationMessageRepository | null = null;
let messageState: ConversationMessageStatePort | null = null;

export const bindConversationApplication = ({
  messageRepository,
  messageStatePort,
}: {
  messageRepository: ConversationMessageRepository;
  messageStatePort: ConversationMessageStatePort;
}): void => {
  repository = messageRepository;
  messageState = messageStatePort;
};

export const getConversationMessageRepository =
  (): ConversationMessageRepository => {
    if (!repository)
      throw new Error("Conversation message repository is not bound");
    return repository;
  };

export const getConversationMessageState = (): ConversationMessageStatePort => {
  if (!messageState) throw new Error("Conversation message state is not bound");
  return messageState;
};

export const loadConversationSnippets = (
  conversations: ConversationSummary[],
): Promise<Record<string, string>> =>
  getConversationMessageRepository().getLastMessages(conversations);
