export type PerfWindow = "1d" | "7d" | "1m" | "3m" | "6m";

export interface PerfTrendBucket {
  bucket: string | null;
  p50_ms: number | null;
  p95_ms: number | null;
  turns: number;
}

export interface PerfResponseTime {
  p50_ms: number | null;
  p95_ms: number | null;
  trend: PerfTrendBucket[];
}

export interface PerfConversion {
  rate_pct: number | null;
  with_phone: number;
  candidate_chats: number;
}

export interface PerfMetrics {
  window: PerfWindow;
  response_time: PerfResponseTime;
  conversion: PerfConversion;
}
