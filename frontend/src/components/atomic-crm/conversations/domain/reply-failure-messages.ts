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

/**
 * Whether a failed/unknown send's `external_error` marks the recipient — not
 * the request — as permanently unreachable, so retrying can never succeed.
 *
 * Proven signals: Zalo OA "user_id is invalid / user_id is not valid"
 * (-201), Messenger code=551 "This person isn't available right now"
 * (blocked/deactivated account), Messenger code=100 subcode=2018001 "No
 * matching user found", and the dispatcher's own skip wording for a PSID
 * already carrying the terminal recipient marker.
 */
export const isUserUnreachableError = (
  externalError: string | null | undefined,
): boolean => {
  const reason = (externalError ?? "").toLowerCase();
  if (!reason) return false;
  return (
    reason.includes("user_id is invalid") ||
    reason.includes("user_id is not valid") ||
    reason.includes("code=551") ||
    reason.includes("subcode=2018001") ||
    reason.includes("recipient terminally unreachable")
  );
};

/**
 * The short Vietnamese failure reason shown on a failed/unknown bubble,
 * channel-aware: a Messenger rejection must not be reported as a Zalo one —
 * the recruiter would debug the wrong integration.
 *
 * `channelProvider` is the conversation's resolved display channel (see
 * `resolveConversationDisplayChannel`); unknown channels fall back to the
 * Zalo wording, matching the neutral-wording fallback used elsewhere.
 */
export const replyFailureReasonLabel = (
  externalError: string | null | undefined,
  channelProvider: ConversationChannelProvider | null,
): string => {
  const reason = (externalError ?? "").toLowerCase();
  if (!reason) return "";
  if (isUserUnreachableError(reason)) {
    return channelProvider === "facebook_messenger"
      ? "Người nhận không liên lạc được qua Messenger — thử lại sẽ không thành công"
      : "Người nhận không liên lạc được qua Zalo — thử lại sẽ không thành công";
  }
  if (
    reason.includes("timeout") ||
    reason.includes("connect") ||
    reason.includes("network")
  ) {
    return "Lỗi kết nối mạng";
  }
  return channelProvider === "facebook_messenger"
    ? "Messenger từ chối tin nhắn"
    : "Zalo từ chối tin nhắn";
};
