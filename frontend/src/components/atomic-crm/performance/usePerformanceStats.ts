import { useQuery } from "@tanstack/react-query";

import { apiJson } from "../providers/rest/api";

// Fetches the per-stage turn-latency bundle from /admin/performance (admin-only).
// Mirrors the useDashboardStats pattern: one TanStack useQuery over apiJson.

export interface StagePercentiles {
  p50: number | null;
  p95: number | null;
  p99: number | null;
}

export interface PerfLive {
  queue_depth: number;
  busy_workers: number;
  total_workers: number;
  llm_avg_latency_ms: number;
  llm_invokes_last_2m: number;
  minimax_429s_last_1m: number;
  llm_fallbacks_last_2m: number;
}

export interface PerfSlowTurn {
  id: number;
  conversation_id: string;
  started_at: string | null;
  outcome: string;
  lane: string | null;
  intent: string | null;
  llm_ms: number | null;
  llm_calls: number | null;
  tool_calls: number | null;
  tool_ms: number | null;
  prefetch_hit: boolean | null;
  pipeline_ms: number | null;
  total_ms: number | null;
  queue_depth: number | null;
}

export interface PerfMetrics {
  window: string;
  live: PerfLive;
  percentiles: Record<string, StagePercentiles>;
  by_lane: Record<string, number>;
  by_outcome: Record<string, number>;
  slow_turns: PerfSlowTurn[];
}

export const usePerformanceStats = (window = "24h") =>
  useQuery<PerfMetrics>({
    queryKey: ["performance-metrics", window],
    queryFn: () =>
      apiJson<PerfMetrics>(`/api/v1/admin/performance?window=${window}`),
    staleTime: 1000 * 30,
  });
