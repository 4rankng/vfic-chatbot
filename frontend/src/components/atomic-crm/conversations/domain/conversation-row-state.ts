type ConversationRowState = {
  id: string;
  mode: "bot" | "human" | "semi_auto" | "closed";
  needs_human?: boolean;
  unread_count?: number;
  last_inbound_at: string | null;
  last_outbound_at?: string | null;
};

type SortableConversationRow = ConversationRowState & {
  updated_at: string;
};

const getConversationModePriority = (mode: ConversationRowState["mode"]) => {
  if (mode === "human") return 0;
  if (mode === "semi_auto") return 1;
  if (mode === "bot") return 2;
  return 3;
};

export const isHumanManagedConversation = (
  conversation: ConversationRowState,
) => conversation.mode === "human" || conversation.mode === "semi_auto";

export const getConversationUnreadCount = (
  conversation: ConversationRowState,
  readIds: ReadonlySet<string>,
) =>
  !isHumanManagedConversation(conversation) || readIds.has(conversation.id)
    ? 0
    : (conversation.unread_count ?? 0);

const hasUnansweredInbound = (conversation: ConversationRowState) => {
  if (!conversation.last_inbound_at) return false;
  if (!conversation.last_outbound_at) return true;
  return (
    new Date(conversation.last_inbound_at).getTime() >
    new Date(conversation.last_outbound_at).getTime()
  );
};

export const needsHumanReply = (conversation: ConversationRowState) =>
  isHumanManagedConversation(conversation) &&
  hasUnansweredInbound(conversation);

export const botHasNotReplied = (conversation: ConversationRowState) =>
  conversation.mode === "bot" && hasUnansweredInbound(conversation);

export const compareConversationRows = (
  first: SortableConversationRow,
  second: SortableConversationRow,
  readIds: ReadonlySet<string>,
): number => {
  const modeDifference =
    getConversationModePriority(first.mode) -
    getConversationModePriority(second.mode);
  if (modeDifference !== 0) return modeDifference;

  const firstNeedsAttention =
    needsHumanReply(first) || botHasNotReplied(first) ? 1 : 0;
  const secondNeedsAttention =
    needsHumanReply(second) || botHasNotReplied(second) ? 1 : 0;
  if (firstNeedsAttention !== secondNeedsAttention) {
    return secondNeedsAttention - firstNeedsAttention;
  }

  const firstUnread = readIds.has(first.id) ? 0 : (first.unread_count ?? 0);
  const secondUnread = readIds.has(second.id) ? 0 : (second.unread_count ?? 0);
  if (firstUnread !== secondUnread) return secondUnread - firstUnread;

  // Match the timestamp each row shows (last_inbound_at, falling back to
  // updated_at) so the order never contradicts the visible times. ``updated_at``
  // alone drifts when batch maintenance touches a row without a new message.
  const firstAt = new Date(first.last_inbound_at ?? first.updated_at).getTime();
  const secondAt = new Date(second.last_inbound_at ?? second.updated_at).getTime();
  return secondAt - firstAt;
};

export const getConversationAttentionLabel = (
  conversation: ConversationRowState,
): string => {
  if (conversation.mode === "closed") return "Đã đóng";
  if (conversation.needs_human) return "Cần xử lý";
  if (botHasNotReplied(conversation)) return "Bot chưa phản hồi";
  if (needsHumanReply(conversation)) return "Chờ nhân viên";
  return "";
};
