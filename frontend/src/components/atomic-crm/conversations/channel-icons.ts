import messengerIcon from "@/assets/channel-adapters/facebook-messenger.svg";
import tingtingOaIcon from "@/assets/channel-adapters/tingting-oa.png";
import zaloChatbotIcon from "@/assets/channel-adapters/zalo-chatbot.png";
import zaloOaIcon from "@/assets/channel-adapters/zalo-oa.png";
import {
  type ConversationChannelProvider,
  isConversationChannelProvider,
} from "../types";

/**
 * The channel glyphs. One source, reused by the channel filter, the conversation
 * list and the thread header — a channel is identified by its icon everywhere,
 * with the full label on the element's `alt`/`title`.
 */
export const CHANNEL_ICONS: Record<ConversationChannelProvider, string> = {
  zalo_bot: zaloChatbotIcon,
  zalo_oa: zaloOaIcon,
  facebook_messenger: messengerIcon,
  tingting_oa: tingtingOaIcon,
};

/** The glyph for a provider of unknown provenance, or `undefined` for "none". */
export const channelIcon = (provider?: string | null): string | undefined => {
  const candidate = provider ?? null;
  return isConversationChannelProvider(candidate)
    ? CHANNEL_ICONS[candidate]
    : undefined;
};
