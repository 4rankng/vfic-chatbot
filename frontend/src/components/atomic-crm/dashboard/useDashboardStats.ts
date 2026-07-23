import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  buildDashboardStats,
  type DashboardMetricsPayload,
  type DashboardStats,
  type KnowledgeIngestHealth,
  type StageBreakdown,
} from "../reporting/domain/dashboardMetrics";
import { getDashboardMetrics } from "../reporting/reportingService";

export type {
  DashboardStats,
  KnowledgeIngestHealth,
  StageBreakdown,
};

export const useDashboardStats = (): DashboardStats => {
  const { data, isPending } = useQuery<DashboardMetricsPayload>({
    queryKey: ["dashboard-metrics"],
    queryFn: () => getDashboardMetrics<DashboardMetricsPayload>(),
    staleTime: 1000 * 30, // 30s — KPI tiles stay fresh on refocus
  });

  return useMemo(
    () => buildDashboardStats(data, isPending),
    [data, isPending],
  );
};
