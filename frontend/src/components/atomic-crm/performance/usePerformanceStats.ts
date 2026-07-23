import { useQuery } from "@tanstack/react-query";

import {
  type PerfAdapterBreakdown,
  type PerfLive,
  type PerfMetrics,
  type PerfReliability,
  type PerfSlowTurn,
  type PerfTrendBucket,
  type StagePercentiles,
} from "../reporting/domain/contracts";
import { getPerformanceMetrics } from "../reporting/reportingService";

// Fetches the per-stage turn-latency bundle from /admin/performance (admin-only).
// Mirrors the useDashboardStats pattern: one TanStack useQuery over apiJson.

export type {
  PerfAdapterBreakdown,
  PerfLive,
  PerfMetrics,
  PerfReliability,
  PerfSlowTurn,
  PerfTrendBucket,
  StagePercentiles,
};

export const usePerformanceStats = (window = "24h") =>
  useQuery<PerfMetrics>({
    queryKey: ["performance-metrics", window],
    queryFn: () => getPerformanceMetrics<PerfMetrics>(window),
    staleTime: 1000 * 30,
  });
