import type { QueryClient } from "@tanstack/react-query";

/**
 * Cache key for the bot-run log: the run list and one run's facts are keyed
 * under it, per identity, so a logout or a terminal 401 can drop every cached
 * run in one call.
 */
export const BOT_RUN_QUERY_KEY = ["bot-runs"] as const;

export const clearBotRunQueries = (queryClient: QueryClient): void => {
  void queryClient.cancelQueries({ queryKey: BOT_RUN_QUERY_KEY });
  queryClient.removeQueries({ queryKey: BOT_RUN_QUERY_KEY });
};
