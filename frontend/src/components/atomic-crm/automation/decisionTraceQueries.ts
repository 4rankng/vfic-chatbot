import type { QueryClient } from "@tanstack/react-query";

export const DECISION_TRACE_QUERY_KEY = ["decision-trace"] as const;

export const clearDecisionTraceQueries = (queryClient: QueryClient): void => {
  void queryClient.cancelQueries({ queryKey: DECISION_TRACE_QUERY_KEY });
  queryClient.removeQueries({ queryKey: DECISION_TRACE_QUERY_KEY });
};
