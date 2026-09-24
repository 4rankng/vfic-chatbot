import { useQuery } from "@tanstack/react-query";

import { apiJson } from "@/lib/apiClient";
import type { Conversation } from "../../types";
import {
  ATTENTION_REFRESH_INTERVAL_MS,
  ATTENTION_ROWS_QUERY_KEY,
} from "./attention-queries";

/** Subset of {@link Conversation} rendered in the bell popover. */
export type NeedsAttentionRow = Pick<
  Conversation,
  "id" | "last_inbound_at" | "contact" | "channel_identity"
>;

interface ConversationListResponse {
  data: NeedsAttentionRow[];
  total: number;
}

/**
 * Recent conversations whose latest inbound message is still unanswered — the
 * same server-side definition that backs the topbar bell badge
 * (`GET /conversations/needs-attention`). The popover shows up to 8 of the
 * freshest rows; the footer link hands off to the full inbox.
 *
 * The query is **gated** by `enabled` so it only fires when the popover opens;
 * the shared attention cadence keeps the open panel fresh.
 */
export const useNeedsAttention = (enabled: boolean) => {
  const query = useQuery<ConversationListResponse>({
    queryKey: ATTENTION_ROWS_QUERY_KEY,
    queryFn: () =>
      apiJson<ConversationListResponse>(
        "/api/v1/conversations?needs_attention=true&per_page=8&sort=last_inbound_at&order=desc",
      ),
    enabled,
    staleTime: ATTENTION_REFRESH_INTERVAL_MS,
    refetchInterval: enabled ? ATTENTION_REFRESH_INTERVAL_MS : false,
  });

  return {
    rows: query.data?.data ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
};
