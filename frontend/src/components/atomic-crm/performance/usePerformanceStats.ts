import { useQuery } from "@tanstack/react-query";

import {
  type PerfConversion,
  type PerfMetrics,
  type PerfResponseTime,
  type PerfTrendBucket,
  type PerfWindow,
} from "../reporting/domain/contracts";
import { getPerformanceMetrics } from "../reporting/reportingService";

// Fetches the two-metric bundle (response time + phone-capture conversion) from
// /admin/performance (admin-only). Mirrors the useDashboardStats pattern: one
// TanStack useQuery over apiJson.

export type {
  PerfConversion,
  PerfMetrics,
  PerfResponseTime,
  PerfTrendBucket,
  PerfWindow,
};

export const usePerformanceStats = (window: PerfWindow = "7d") =>
  useQuery<PerfMetrics>({
    queryKey: ["performance-metrics", window],
    queryFn: () => getPerformanceMetrics<PerfMetrics>(window),
    staleTime: 1000 * 30,
  });
