import { useAttentionCounts } from "./useAttentionCounts";

/**
 * Counts conversations where the latest user message is still unanswered.
 * Computed server-side via GET /conversations/needs-attention so navigation
 * badges never load conversation rows.
 *
 * Thin accessor over {@link useAttentionCounts}: the workspace shell and the
 * inbox adapter selector share one polling query instead of polling the same
 * endpoint independently.
 */
export const useNotifications = () => {
  const { total } = useAttentionCounts();
  return { count: total };
};
