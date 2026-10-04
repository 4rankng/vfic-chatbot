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
}

export interface PerfSlowTurn {
  id: number;
  conversation_id: string;
  started_at: string | null;
  outcome: string;
  lane: string | null;
  intent: string | null;
  llm_queue_ms: number | null;
  llm_model_ms: number | null;
  llm_backoff_ms: number | null;
  llm_calls: number | null;
  llm_call_ms: number[] | null;
  tool_calls: number | null;
  tool_ms: number | null;
  tool_breakdown: Record<string, number> | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  cached_tokens: number | null;
  retried_429: boolean | null;
  degraded: boolean | null;
  prefetch_hit: boolean | null;
  pipeline_ms: number | null;
  total_ms: number | null;
  queue_depth: number | null;
  outbound_adapter: string | null;
  outbound_prepare_ms: number | null;
  outbound_provider_ms: number | null;
  outbound_provider_attempts: number | null;
  outbound_retry_count: number | null;
  outbound_retry_ms: number | null;
  outbound_refresh_count: number | null;
  outbound_refresh_ms: number | null;
  outbound_chunk_count: number | null;
  outbound_result: string | null;
  db_ms: number | null;
  db_breakdown: Record<string, number> | null;
  faq_bypass_ms: number | null;
  model_tier: string | null;
  system_prompt_cache_hit: boolean | null;
  dark_time_ms: number | null;
}

export interface PerfTrendBucket {
  bucket: string | null;
  p95_ms: number | null;
  p50_ms: number | null;
  turns: number;
  errors: number;
}

export interface PerfReliability {
  send_unknown_count: number;
  suppressed_count: number;
  failed_count: number;
}

/** Turn-quality and token aggregates over the selected window. */
export interface PerfQuality {
  degraded_count: number;
  retried_429_count: number;
  /** Percent of turns that hit the system-prompt cache; null when unreported. */
  prompt_cache_hit_rate: number | null;
  prompt_tokens_total: number;
  completion_tokens_total: number;
  cached_tokens_total: number;
}

export interface PerfAdapterBreakdown {
  adapter: string;
  turns: number;
  sent: number;
  unsent: number;
  provider_p50_ms: number | null;
  provider_p95_ms: number | null;
  end_to_end_p50_ms: number | null;
  end_to_end_p95_ms: number | null;
  retry_count: number;
  refresh_count: number;
}

export interface PerfMetrics {
  window: string;
  live: PerfLive;
  percentiles: Record<string, StagePercentiles>;
  by_lane: Record<string, number>;
  by_outcome: Record<string, number>;
  by_adapter?: PerfAdapterBreakdown[];
  slow_turns: PerfSlowTurn[];
  trend: PerfTrendBucket[];
  reliability?: PerfReliability;
  quality?: PerfQuality;
}
