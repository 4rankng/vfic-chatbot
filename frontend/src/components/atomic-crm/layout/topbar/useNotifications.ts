import { useQuery } from "@tanstack/react-query";

import { apiJson } from "../../providers/rest/api";

interface NeedsAttentionResponse {
  count: number;
}

/**
 * Counts conversations that need attention: unread inbound messages (real
 * unread_count, kept in sync by the vfic_chat_histories_unread trigger) OR an
 * active recruiter handoff (mode === "human"). Computed server-side via
 * GET /conversations/needs-attention so the bell never loads conversation rows
 * (the previous useGetList(perPage=500) exceeded the per_page<=200 list cap and
 * filtered client-side). Shared by the desktop and mobile topbar bells so both
 * stay in sync.
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
