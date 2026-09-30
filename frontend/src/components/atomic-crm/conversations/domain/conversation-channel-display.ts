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
    }
  | null
  | undefined;

/**
 * The channel a conversation displays as.
 *
 * Both Zalo OA accounts share one provider id (`zalo_oa`), so a raw provider
 * alone renders "Zalo OA" on rows that belong to the TingTing support account
 * — which read as "the filter does nothing" once the TingTing OA filter is
 * active. Narrow by account_key: the TingTing account displays as the
 * dedicated `tingting_oa` channel (labels in CONVERSATION_CHANNEL_*_LABELS,
 * glyph in CHANNEL_ICONS, `[data-channel="tingting_oa"]` styling), and every
 * other row keeps its raw provider. Unknown or absent providers resolve to
 * `null`; callers fall back to their neutral wording via the types.ts helpers.
 */
export const resolveConversationDisplayChannel = (
  identity: ConversationChannelIdentitySource,
): ConversationChannelProvider | null => {
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
