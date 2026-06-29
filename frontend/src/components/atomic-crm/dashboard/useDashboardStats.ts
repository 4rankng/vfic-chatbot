import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { LEAD_STAGES } from "../types";
import { apiJson } from "../providers/rest/api";

// Funnel KPIs (total leads, per-stage breakdown, qualified/hired rate, human
// takeover count) all derive from ONE server-side aggregate — GET
// /dashboard/metrics — not a client-side dump of lead/conversation rows. The
// previous useGetList(perPage=N) design exceeded the per_page<=200 list cap
// (422) when N>200 and undercounted the funnel silently when N<=200; the
// backend now COUNTs/GROUP BYs in one scoped query and ships only the totals.

interface StageBreakdownItem {
  value: string;
  count: number;
  percentage: number;
}

interface DashboardMetrics {
  open_conversations?: number | null;
  hot_leads?: number | null;
  pending_followups?: number | null;
  bot_suppression_rate?: number | null;
  failed_zalo_sends?: number | null;
  bot_errors?: number | null;
  bot_run_count?: number | null;
  bot_sent_count?: number | null;
  bot_suppressed_count?: number | null;
  bot_success_rate?: number | null;
  avg_bot_response_seconds?: number | null;
  // Concurrent-load monitoring (chatbot readiness)
  webhook_queue_depth?: number | null;
  active_turns?: number | null;
  p95_bot_response_seconds?: number | null;
  turns_last_5min?: number | null;
  total_leads?: number | null;
  qualified_count?: number | null;
  hired_count?: number | null;
  hired_rate?: number | null;
  unread_conversation_count?: number | null;
  stage_breakdown?: StageBreakdownItem[] | null;
  knowledge_ingest: KnowledgeIngestHealth | null;
}

export interface StageBreakdown {
  value: string;
  label: string;
  color: string;
  count: number;
  percentage: number;
}

export interface KnowledgeIngestStageMetric {
  stage: string;
  count: number;
}

export interface KnowledgeIngestIssue {
  id: string;
  file_name: string;
  project_id?: string | null;
  status: string;
  stage: string;
  minutes_since_update: number;
  error?: string | null;
}

export interface KnowledgeIngestHealth {
  queue_depth: number;
  failed_job_count: number;
  worker_count: number;
  processing_count: number;
  stuck_count: number;
  failed_document_count: number;
  published_document_count: number;
  stage_breakdown: KnowledgeIngestStageMetric[];
  recent_issues: KnowledgeIngestIssue[];
}

export interface DashboardStats {
  openConversations: number;
  hotLeads: number;
  pendingFollowups: number;
  botSuppressionRate: number;
  failedZaloSends: number;
  botErrors: number;
  botRunCount: number;
  botSentCount: number;
  botSuppressedCount: number;
  botSuccessRate: number;
  avgBotResponseSeconds: number;
  webhookQueueDepth: number;
  activeTurns: number;
  p95BotResponseSeconds: number;
  turnsLast5min: number;
  totalLeads: number;
  qualifiedCount: number;
  unreadConversationCount: number;
  hiredRate: number;
  stageBreakdown: StageBreakdown[];
  knowledgeIngest: KnowledgeIngestHealth | null;
  isPending: boolean;
}

const numberOrZero = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;

const percentOrZero = (value: unknown): number => numberOrZero(value);

const rateOrZero = (value: unknown): number => numberOrZero(value);

const normalizeKnowledgeIngest = (
  ingest: KnowledgeIngestHealth | null | undefined,
): KnowledgeIngestHealth | null => {
  if (!ingest) return null;

  return {
    queue_depth: numberOrZero(ingest.queue_depth),
    failed_job_count: numberOrZero(ingest.failed_job_count),
    worker_count: numberOrZero(ingest.worker_count),
    processing_count: numberOrZero(ingest.processing_count),
    stuck_count: numberOrZero(ingest.stuck_count),
    failed_document_count: numberOrZero(ingest.failed_document_count),
    published_document_count: numberOrZero(ingest.published_document_count),
    stage_breakdown: (ingest.stage_breakdown ?? []).map((row) => ({
      stage: row.stage,
      count: numberOrZero(row.count),
    })),
    recent_issues: ingest.recent_issues ?? [],
  };
};

export const useDashboardStats = (): DashboardStats => {
  const { data, isPending } = useQuery<DashboardMetrics>({
    queryKey: ["dashboard-metrics"],
    queryFn: () => apiJson<DashboardMetrics>("/api/v1/dashboard/metrics"),
    staleTime: 1000 * 30, // 30s — KPI tiles stay fresh on refocus
  });

  return useMemo<DashboardStats>(() => {
    if (!data) {
      return {
        openConversations: 0,
        hotLeads: 0,
        pendingFollowups: 0,
        botSuppressionRate: 0,
        failedZaloSends: 0,
        botErrors: 0,
        botRunCount: 0,
        botSentCount: 0,
        botSuppressedCount: 0,
        botSuccessRate: 0,
        avgBotResponseSeconds: 0,
        webhookQueueDepth: 0,
        activeTurns: 0,
        p95BotResponseSeconds: 0,
        turnsLast5min: 0,
        totalLeads: 0,
        qualifiedCount: 0,
        unreadConversationCount: 0,
        hiredRate: 0,
        stageBreakdown: [],
        knowledgeIngest: null,
        isPending,
      };
    }
    // Merge the server's value+count+percentage into the canonical LEAD_STAGES
    // order/label/color so the funnel renders consistently even for zero-count
    // stages (which the backend emits too).
    const botRunCount = numberOrZero(data.bot_run_count);
    const botSentCount = numberOrZero(data.bot_sent_count);
    const botSuppressedCount = numberOrZero(data.bot_suppressed_count);
    const hiredCount = numberOrZero(data.hired_count);
    const totalLeads = numberOrZero(data.total_leads);
    const botSuccessRate =
      data.bot_success_rate == null && botRunCount > 0
        ? (botSentCount / botRunCount) * 100
        : percentOrZero(data.bot_success_rate);
    const botSuppressionRate =
      data.bot_suppression_rate == null && botRunCount > 0
        ? botSuppressedCount / botRunCount
        : rateOrZero(data.bot_suppression_rate);
    const hiredRate =
      data.hired_rate == null && totalLeads > 0
        ? (hiredCount / totalLeads) * 100
        : percentOrZero(data.hired_rate);
    const byValue = new Map(
      (data.stage_breakdown ?? []).map((s) => [s.value, s]),
    );
    return {
      openConversations: numberOrZero(data.open_conversations),
      hotLeads: numberOrZero(data.hot_leads),
      pendingFollowups: numberOrZero(data.pending_followups),
      botSuppressionRate,
      failedZaloSends: numberOrZero(data.failed_zalo_sends),
      botErrors: numberOrZero(data.bot_errors),
      botRunCount,
      botSentCount,
      botSuppressedCount,
      botSuccessRate,
      avgBotResponseSeconds: numberOrZero(data.avg_bot_response_seconds),
      webhookQueueDepth: numberOrZero(data.webhook_queue_depth),
      activeTurns: numberOrZero(data.active_turns),
      p95BotResponseSeconds: numberOrZero(data.p95_bot_response_seconds),
      turnsLast5min: numberOrZero(data.turns_last_5min),
      totalLeads,
      qualifiedCount: numberOrZero(data.qualified_count),
      unreadConversationCount: numberOrZero(data.unread_conversation_count),
      hiredRate,
      knowledgeIngest: normalizeKnowledgeIngest(data.knowledge_ingest),
      stageBreakdown: LEAD_STAGES.map((stage) => {
        const row = byValue.get(stage.value);
        return {
          value: stage.value,
          label: stage.label,
          color: stage.color,
          count: numberOrZero(row?.count),
          percentage: percentOrZero(row?.percentage),
        };
      }),
      isPending,
    };
  }, [data, isPending]);
};
