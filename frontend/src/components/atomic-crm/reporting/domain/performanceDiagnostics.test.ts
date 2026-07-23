import { describe, expect, it } from "vitest";

import type { PerfSlowTurn } from "../../performance/usePerformanceStats";
import {
  formatCompactDuration,
  formatMetricDuration,
  getSlowTurnTone,
  getStageTone,
  likelyBottleneck,
} from "./performanceDiagnostics";

const turn = (overrides: Partial<PerfSlowTurn> = {}): PerfSlowTurn => ({
  id: 1,
  conversation_id: "conv-1",
  started_at: "2026-07-23T00:00:00Z",
  outcome: "SENT",
  lane: "agent",
  intent: null,
  llm_queue_ms: 500,
  llm_model_ms: 8000,
  llm_backoff_ms: null,
  llm_calls: 1,
  llm_call_ms: null,
  tool_calls: 0,
  tool_ms: 50,
  tool_breakdown: null,
  prompt_tokens: null,
  completion_tokens: null,
  cached_tokens: null,
  retried_429: false,
  degraded: false,
  prefetch_hit: false,
  pipeline_ms: 1000,
  total_ms: 9000,
  queue_depth: 1,
  outbound_adapter: null,
  outbound_prepare_ms: null,
  outbound_provider_ms: null,
  outbound_provider_attempts: null,
  outbound_retry_count: null,
  outbound_retry_ms: null,
  outbound_refresh_count: null,
  outbound_refresh_ms: null,
  outbound_chunk_count: null,
  outbound_result: null,
  db_ms: 400,
  db_breakdown: null,
  faq_bypass_ms: 300,
  model_tier: null,
  system_prompt_cache_hit: null,
  dark_time_ms: null,
  ...overrides,
});

describe("performance diagnostics", () => {
  it("formats durations for dense and compact displays", () => {
    expect(formatMetricDuration(1200)).toBe("1.2 giây");
    expect(formatCompactDuration(1200)).toBe("1.2s");
    expect(formatMetricDuration(null)).toBe("Chưa có");
  });

  it("marks slow stages and slow turns with warning/danger tones", () => {
    expect(getStageTone("end_to_end", 16_000)).toBe("danger");
    expect(getStageTone("end_to_end", 11_000)).toBe("warning");
    expect(getSlowTurnTone(turn({ total_ms: 21_000 }))).toBe("danger");
    expect(getSlowTurnTone(turn({ retried_429: true }))).toBe("warning");
  });

  it("describes the largest bottleneck stage", () => {
    expect(
      likelyBottleneck(turn({ llm_model_ms: 8000, db_ms: 2000, faq_bypass_ms: 300 })),
    ).toBe("LLM xử lý (8.0s)");
  });
});
