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

export const CONVERSATION_CHANNEL_PROVIDERS = [
  "zalo_bot",
  "zalo_oa",
  "facebook_messenger",
] as const;

export type ConversationChannelProvider =
  (typeof CONVERSATION_CHANNEL_PROVIDERS)[number];

export type SearchParameterReader = {
  get(name: string): string | null;
};

export const isConversationChannelProvider = (
  value: string | null,
): value is ConversationChannelProvider =>
  value !== null &&
  CONVERSATION_CHANNEL_PROVIDERS.some((provider) => provider === value);

export const getEffectiveConversationChannelProvider = (
  searchParams: SearchParameterReader,
): ConversationChannelProvider | undefined => {
  const provider = searchParams.get("channel_provider");
  return isConversationChannelProvider(provider) ? provider : undefined;
};

export const isAttentionReason = (value: string | null): value is string =>
  value !== null && ATTENTION_REASON_KEYS.has(value);

export type ConversationListServerFilter = {
  channel_provider?: ConversationChannelProvider;
  reason?: string;
  needs_attention?: true;
};

export const getConversationListServerFilter = (
  searchParams: SearchParameterReader,
): ConversationListServerFilter => {
  const channel_provider =
    getEffectiveConversationChannelProvider(searchParams);
  const providerFilter = channel_provider ? { channel_provider } : {};
  const reasonParam = searchParams.get("reason");
  if (isAttentionReason(reasonParam)) {
    return { ...providerFilter, reason: reasonParam };
  }
  return searchParams.get("needs_attention") === "true"
    ? { ...providerFilter, needs_attention: true }
    : providerFilter;
};

export const getConversationListKey = (
  filter: ConversationListServerFilter,
): string => {
  const context = filter.reason
    ? `reason:${filter.reason}`
    : filter.needs_attention
      ? "needs-attention"
      : "all";
  return `${filter.channel_provider ?? "all"}:${context}`;
};

export const getChannelProviderSearchParams = (
  searchParams: URLSearchParams,
  provider: ConversationChannelProvider,
): URLSearchParams => {
  const next = new URLSearchParams(searchParams);
  next.set("channel_provider", provider);
  next.delete("id");
  return next;
};
