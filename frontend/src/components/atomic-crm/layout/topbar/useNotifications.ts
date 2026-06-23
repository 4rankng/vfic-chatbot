import { useGetList } from "ra-core";

import type { Conversation } from "../../types";

/**
 * Counts conversations that need attention: unread inbound messages (real
 * unread_count, kept in sync by the vfic_chat_histories_unread trigger) OR an
 * active recruiter handoff (mode === "human"). Unioning both keeps the bell
 * honest without regressing the previous handoff-only signal.
 * Shared by the desktop and mobile topbar bells so both stay in sync.
 */
export const useNotifications = () => {
  const { data: conversations } = useGetList<Conversation>("conversations", {
    pagination: { page: 1, perPage: 500 },
  });

  const count =
    conversations?.filter(
      (conversation) =>
        (conversation.unread_count ?? 0) > 0 ||
        conversation.mode === "human",
    ).length ?? 0;

  return { count, hasNotifications: count > 0 };
};
