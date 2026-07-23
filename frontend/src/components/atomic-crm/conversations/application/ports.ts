import type { ConversationMessage } from "../domain/conversation-message";

export type ConversationSummary = {
  id: string;
  zalo_chat_id?: string | null;
};

export type ConversationMessagePage = {
  messages: ConversationMessage[];
  hasMore: boolean;
};

export interface CancellationSignal {
  readonly aborted: boolean;
}

export type ConversationMessageQuery = {
  limit?: number;
  beforeId?: string;
  signal?: CancellationSignal;
};

export interface ConversationMessageRepository {
  getLastMessages(
    conversations: ConversationSummary[],
  ): Promise<Record<string, string>>;
  getConversationMessages(
    conversationId: string,
    options?: ConversationMessageQuery,
  ): Promise<ConversationMessagePage>;
  getMessagesSince(
    conversationId: string,
    sinceId: string,
  ): Promise<ConversationMessagePage>;
  getMessageCount(zaloChatId: string): Promise<number>;
  subscribeToMessages(
    conversationId: string,
    onNewMessages: (messages: ConversationMessage[]) => void,
  ): () => void;
  subscribeToConnection(
    onConnect: () => void,
    onDisconnect: () => void,
  ): () => void;
  isConnected(): boolean;
}

export interface RuntimeEpochPort {
  capture(): number;
  isCurrent(epoch: number): boolean;
}
