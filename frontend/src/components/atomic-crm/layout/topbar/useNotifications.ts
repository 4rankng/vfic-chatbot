import { useQuery } from "@tanstack/react-query";

import { apiJson } from "@/lib/apiClient";

interface NeedsAttentionResponse {
  count: number;
}

/**
 * Counts conversations where the latest user message is still unanswered.
 * Computed server-side via GET /conversations/needs-attention so navigation
 * badges never load conversation rows.
 */
export const useNotifications = () => {
  const { data } = useQuery<NeedsAttentionResponse>({
    queryKey: ["conversations-needs-attention"],
    queryFn: () =>
      apiJson<NeedsAttentionResponse>("/api/v1/conversations/needs-attention"),
    staleTime: 1000 * 30,
    // `staleTime` only permits a refetch; it does not schedule one for this
    // continuously mounted workspace query. Poll at the same cadence so a
    // completed reply cannot leave a stale navigation badge behind.
    refetchInterval: 1000 * 30,
  });

  const count = data?.count ?? 0;
  return { count };
};
