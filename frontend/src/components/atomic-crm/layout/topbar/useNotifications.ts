import { useQuery } from "@tanstack/react-query";

import { apiJson } from "../../providers/rest/api";

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
  });

  const count = data?.count ?? 0;
  return { count };
};
