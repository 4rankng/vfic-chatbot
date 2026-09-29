import {
  CONVERSATION_CHANNEL_PROVIDERS,
  isConversationChannelProvider,
  type ConversationChannelProvider,
} from "./conversation-list-filters";

/**
 * The one Vietnamese label per conversation channel. Every surface that names a
 * channel — the inbox adapter selector, the notification rows, the performance
 * adapter matrix and the persona assignment rows — reads this map, so a channel
 * is never labelled two different ways.
 */
export const CONVERSATION_CHANNEL_LABELS: Record<
  ConversationChannelProvider,
  string
> = {
  zalo_bot: "Zalo Chatbot",
  zalo_oa: "Zalo OA",
  facebook_messenger: "Messenger",
  // The employee-support OA: provider zalo_oa, narrowed to the linked account.
  tingting_oa: "Zalo OA TingTing (hỗ trợ nhân viên)",
};

/** Provider ids the API can put on a conversation row, for exhaustiveness. */
export const CONVERSATION_CHANNEL_LABEL_VALUES = CONVERSATION_CHANNEL_PROVIDERS;

/**
 * Label for a raw provider string from the API. Unknown or absent providers
 * read as a neutral channel rather than as an empty cell.
 */
export const conversationChannelLabel = (
  provider: string | null | undefined,
): string =>
  isConversationChannelProvider(provider ?? null)
    ? CONVERSATION_CHANNEL_LABELS[provider as ConversationChannelProvider]
    : "Kênh khác";
