import {
  isConversationChannelProvider,
  type ConversationChannelProvider,
} from "../../types";

/**
 * The account_key the backend stamps on zalo_oa rows of the TingTing
 * employee-support OA (backend app/channels/types.py
 * `TINGTING_OA_ACCOUNT_KEY`). Duplicated as a literal: frontend domain layers
 * cannot import backend modules.
 */
const TINGTING_OA_ACCOUNT_KEY = "tingting";

/** The slice of `Conversation["channel_identity"]` the resolution reads. */
export type ConversationChannelIdentitySource =
  | {
      provider?: string | null;
      account_key?: string | null;
      /** Server-derived badge channel (schemas/conversation.py
       * `channel_display`): the raw account_key never reaches the client, so
       * the backend narrows the TingTing OA before masking. */
      display_channel?: string | null;
    }
  | null
  | undefined;

/**
 * The channel a conversation displays as.
 *
 * Prefers the server-derived `display_channel`; the raw `account_key` path
 * below only serves responses from a backend that predates it (and is inert
 * in production, where `account_key` arrives masked). Unknown or absent
 * providers resolve to `null`; callers fall back to their neutral wording via
 * the types.ts helpers.
 */
export const resolveConversationDisplayChannel = (
  identity: ConversationChannelIdentitySource,
): ConversationChannelProvider | null => {
  const fromApi = identity?.display_channel ?? null;
  if (isConversationChannelProvider(fromApi)) return fromApi;
  const provider = identity?.provider ?? null;
  if (!isConversationChannelProvider(provider)) return null;
  if (
    provider === "zalo_oa" &&
    identity?.account_key === TINGTING_OA_ACCOUNT_KEY
  ) {
    return "tingting_oa";
  }
  return provider;
};
