import type {
  ConversationContextValue,
  ConversationRowPresentation,
} from "../../capabilities/types";
import type { Conversation } from "../../types";

const genericName = (conversation: Conversation): string =>
  conversation.contact?.display_name?.trim() ||
  `Liên hệ · ${(conversation.channel_identity?.external_id || conversation.zalo_chat_id || "").slice(-6)}`;

export const getGenericConversationPresentation = (
  conversation: Conversation,
): ConversationRowPresentation => {
  const displayName = genericName(conversation);
  const subtitle = conversation.contact?.primary_phone?.trim() || "";
  return {
    displayName,
    subtitle,
    avatarUrl: conversation.contact?.avatar_url,
    avatarBackground: "var(--muted)",
    avatarForeground: "var(--muted-foreground)",
    searchText: [
      displayName,
      subtitle,
      conversation.contact?.primary_email,
      conversation.channel_identity?.external_id,
      conversation.zalo_chat_id,
    ]
      .filter(Boolean)
      .join(" "),
  };
};

export const getGenericConversationContext = (
  conversation: Conversation | undefined,
): ConversationContextValue => {
  const displayName = conversation ? genericName(conversation) : "Liên hệ";
  const phone = conversation?.contact?.primary_phone?.trim() || undefined;
  return {
    displayName,
    avatarUrl: conversation?.contact?.avatar_url,
    avatarBackground: "var(--muted)",
    avatarForeground: "var(--muted-foreground)",
    contactSubtitle: phone ? { phone } : undefined,
    avatarAlt: `Ảnh đại diện của ${displayName}`,
    panelLabel: "thông tin liên hệ",
  };
};
