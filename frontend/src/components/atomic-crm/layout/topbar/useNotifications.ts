import { useGetList } from "ra-core";

import type { Conversation } from "../../types";

/**
 * Counts conversations that need a human response (mode === "human").
 * Shared by the desktop and mobile topbar bells so both stay in sync, and
 * mirrors the fetch-then-filter idiom used elsewhere (Dashboard, the original
 * mobile bell).
 */
export const useNotifications = () => {
  const { data: conversations } = useGetList<Conversation>("conversations", {
    pagination: { page: 1, perPage: 100 },
  });

  const count =
    conversations?.filter((conversation) => conversation.mode === "human")
      .length ?? 0;

  return { count, hasNotifications: count > 0 };
};
