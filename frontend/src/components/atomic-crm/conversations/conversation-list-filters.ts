const ATTENTION_REASON_KEYS = new Set([
  "DELIVERY_REVIEW",
  "HUMAN_ESCALATION",
  "REPLY_OVERDUE",
  "FOLLOWUP_OVERDUE",
  "WAITING_REPLY",
  "PRIORITY_NO_ACTION",
  "FOLLOWUP_TODAY",
  "UNREAD",
  "STALLED",
]);

export const isAttentionReason = (value: string | null): value is string =>
  value !== null && ATTENTION_REASON_KEYS.has(value);

type ConversationListServerFilter =
  | { reason: string }
  | { needs_attention: true }
  | undefined;

/** Converts inbox deep links into the filter accepted by the conversations API. */
export const getConversationListServerFilter = (
  searchParams: URLSearchParams,
): ConversationListServerFilter => {
  const reasonParam = searchParams.get("reason");
  if (isAttentionReason(reasonParam)) return { reason: reasonParam };
  return searchParams.get("needs_attention") === "true"
    ? { needs_attention: true }
    : undefined;
};
