import { useQuery } from "@tanstack/react-query";

import { apiJson } from "../../providers/rest/api";

interface NeedsAttentionResponse {
  count: number;
}

/**
 * Counts conversations where the latest user message is still unanswered.
 * Computed server-side via GET /conversations/needs-attention so the bell never
 * loads conversation rows. Shared by the desktop and mobile topbar bells so
 * both stay in sync.
 */
export const useNotifications = () => {
  const { data } = useQuery<NeedsAttentionResponse>({
    queryKey: ["conversations-needs-attention"],
    queryFn: () =>
      apiJson<NeedsAttentionResponse>("/api/v1/conversations/needs-attention"),
    staleTime: 1000 * 30,
  });

  const count = data?.count ?? 0;
  return { count, hasNotifications: count > 0 };
};
