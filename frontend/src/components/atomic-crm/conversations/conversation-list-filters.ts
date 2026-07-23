export {
  CONVERSATION_CHANNEL_PROVIDERS,
  getConversationListKey,
  getConversationListServerFilter,
  getEffectiveConversationChannelProvider,
  isAttentionReason,
  isConversationChannelProvider,
} from "./domain/conversation-list-filters";
export type {
  ConversationChannelProvider,
  ConversationListServerFilter,
} from "./domain/conversation-list-filters";

import type { ConversationChannelProvider } from "./domain/conversation-list-filters";

export const getChannelProviderSearchParams = (
  searchParams: URLSearchParams,
  provider: ConversationChannelProvider,
): URLSearchParams => {
  const next = new URLSearchParams(searchParams);
  next.set("channel_provider", provider);
  next.delete("id");
  return next;
};
