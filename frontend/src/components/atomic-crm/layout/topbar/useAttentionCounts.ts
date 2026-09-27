import { useQuery } from "@tanstack/react-query";

import { apiJson } from "@/lib/apiClient";
import {
  CONVERSATION_CHANNEL_PROVIDERS,
  type ConversationChannelProvider,
} from "../../conversations/domain/conversation-list-filters";
import {
  ATTENTION_COUNTS_QUERY_KEY,
  ATTENTION_REFRESH_INTERVAL_MS,
} from "./attention-queries";

const NEEDS_ATTENTION_PATH = "/api/v1/conversations/needs-attention";

interface NeedsAttentionCountResponse {
  count: number;
}

type AttentionCounts = {
  /** Unscoped count: the number the topbar bell and the rail badge ring for. */
  total: number;
  /** The same server-side definition, split by the channel it arrived on. */
  byProvider: Readonly<Record<ConversationChannelProvider, number>>;
};

const ZERO_BY_PROVIDER: Record<ConversationChannelProvider, number> = {
  zalo_bot: 0,
  zalo_oa: 0,
  facebook_messenger: 0,
  tingting_oa: 0,
};

const NO_ATTENTION_COUNTS: AttentionCounts = {
  total: 0,
  byProvider: ZERO_BY_PROVIDER,
};

const fetchAttentionCount = async (
  provider?: ConversationChannelProvider,
): Promise<number> => {
  const path = provider
    ? `${NEEDS_ATTENTION_PATH}?channel_provider=${encodeURIComponent(provider)}`
    : NEEDS_ATTENTION_PATH;
  const { count } = await apiJson<NeedsAttentionCountResponse>(path);
  return count;
};

/**
 * Every needs-attention counter the workspace renders, from ONE query.
 *
 * `GET /conversations/needs-attention` answers with a single `{count}`, so the
 * per-provider split needs one request per provider; the query fans those out
 * behind a single cache entry, key and interval instead of three separately
 * mounted pollers. Mounting this hook in the topbar and in the inbox panel
 * shares one polling query per open tab.
 *
 * The unscoped count stays server-authoritative rather than being summed from
 * the provider buckets: `contact_channel_identities.provider` is a free-form
 * column, so the providers the UI lists are not guaranteed to partition the
 * set and a derived total could silently undercount the bell.
 *
 * Polling rather than socket invalidation because `message.created` is only
 * emitted to the `conv:<id>` room a client joins by opening that conversation
 * (`_room_for_payload` in the backend socket server), so an open inbox has no
 * realtime signal for the conversations it is not viewing.
 */
export const useAttentionCounts = (): AttentionCounts => {
  const { data } = useQuery<AttentionCounts>({
    queryKey: ATTENTION_COUNTS_QUERY_KEY,
    queryFn: async () => {
      const [total, providerCounts] = await Promise.all([
        fetchAttentionCount(),
        Promise.all(
          CONVERSATION_CHANNEL_PROVIDERS.map(async (provider) => ({
            provider,
            count: await fetchAttentionCount(provider),
          })),
        ),
      ]);

      return {
        total,
        byProvider: providerCounts.reduce<
          Record<ConversationChannelProvider, number>
        >(
          (counts, { provider, count }) => {
            counts[provider] = count;
            return counts;
          },
          { ...ZERO_BY_PROVIDER },
        ),
      };
    },
    staleTime: ATTENTION_REFRESH_INTERVAL_MS,
    refetchInterval: ATTENTION_REFRESH_INTERVAL_MS,
  });

  return data ?? NO_ATTENTION_COUNTS;
};
