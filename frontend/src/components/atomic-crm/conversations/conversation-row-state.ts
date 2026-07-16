import type { Conversation } from "../types";

export const isHumanManagedConversation = (conversation: Conversation) =>
  conversation.mode === "human" || conversation.mode === "semi_auto";

export const getConversationUnreadCount = (
  conversation: Conversation,
  readIds: ReadonlySet<string>,
) =>
  !isHumanManagedConversation(conversation) || readIds.has(conversation.id)
    ? 0
    : (conversation.unread_count ?? 0);

const hasUnansweredInbound = (conversation: Conversation) => {
  if (!conversation.last_inbound_at) return false;
  if (!conversation.last_outbound_at) return true;
  return (
    new Date(conversation.last_inbound_at).getTime() >
    new Date(conversation.last_outbound_at).getTime()
  );
};

export const needsHumanReply = (conversation: Conversation) =>
  isHumanManagedConversation(conversation) && hasUnansweredInbound(conversation);

export const botHasNotReplied = (conversation: Conversation) =>
  conversation.mode === "bot" && hasUnansweredInbound(conversation);

export const getConversationAttentionLabel = (conversation: Conversation): string => {
  if (conversation.mode === "closed") return "Đã đóng";
  if (conversation.needs_human) return "Cần xử lý";
  if (botHasNotReplied(conversation)) return "Bot chưa phản hồi";
  if (needsHumanReply(conversation)) return "Chờ nhân viên";
  return "";
};
