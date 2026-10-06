import type { ConversationChannelProvider } from "../../types";
import {
  resolveConversationDisplayChannel,
  type ConversationChannelIdentitySource,
} from "./conversation-channel-display";

/**
 * The i18n key for a reply-failure toast.
 *
 * The channel-naming statuses (`unavailable` / `provider`) exist once per
 * delivery channel because their Vietnamese copy names it — a Messenger
 * rejection reported as "Zalo chưa nhận được tin nhắn" sends the recruiter
 * debugging the wrong integration. Every other status is channel-neutral and
 * keeps the shared `reply` key.
 *
 * `identity` is the conversation's `channel_identity` slice; unknown or
 * absent providers resolve to the shared (Zalo-worded) key, matching the
 * neutral-wording fallback used elsewhere.
 */
export const replyFailureMessageKey = (
  status: string,
  identity: ConversationChannelIdentitySource,
): string => {
  if (status === "unavailable" || status === "provider") {
    const channel: ConversationChannelProvider | null =
      resolveConversationDisplayChannel(identity);
    if (channel === "facebook_messenger") {
      return `resources.conversations.reply_messenger.${status}`;
    }
  }
  return `resources.conversations.reply.${status}`;
};
