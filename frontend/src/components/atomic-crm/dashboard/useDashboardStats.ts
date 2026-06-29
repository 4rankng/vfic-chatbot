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
  open_conversations: number;
  hot_leads: number;
  pending_followups: number;
  bot_suppression_rate: number;
  failed_zalo_sends: number;
  bot_errors: number;
  bot_run_count: number;
  bot_sent_count: number;
  bot_suppressed_count: number;
  bot_success_rate: number;
  avg_bot_response_seconds: number;
  total_leads: number;
  qualified_count: number;
  hired_count: number;
  hired_rate: number;
  unread_conversation_count: number;
  stage_breakdown: StageBreakdownItem[];
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
  totalLeads: number;
  qualifiedCount: number;
  unreadConversationCount: number;
  hiredRate: number;
  stageBreakdown: StageBreakdown[];
  knowledgeIngest: KnowledgeIngestHealth | null;
  isPending: boolean;
}

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
    const byValue = new Map(data.stage_breakdown.map((s) => [s.value, s]));
    return {
      openConversations: data.open_conversations,
      hotLeads: data.hot_leads,
      pendingFollowups: data.pending_followups,
      botSuppressionRate: data.bot_suppression_rate,
      failedZaloSends: data.failed_zalo_sends,
      botErrors: data.bot_errors,
      botRunCount: data.bot_run_count,
      botSentCount: data.bot_sent_count,
      botSuppressedCount: data.bot_suppressed_count,
      botSuccessRate: data.bot_success_rate,
      avgBotResponseSeconds: data.avg_bot_response_seconds,
      totalLeads: data.total_leads,
      qualifiedCount: data.qualified_count,
      unreadConversationCount: data.unread_conversation_count,
      hiredRate: data.hired_rate,
      knowledgeIngest: data.knowledge_ingest,
      stageBreakdown: LEAD_STAGES.map((stage) => {
        const row = byValue.get(stage.value);
        return {
          value: stage.value,
          label: stage.label,
          color: stage.color,
          count: row?.count ?? 0,
          percentage: row?.percentage ?? 0,
        };
      }),
      isPending,
    };
  }, [data, isPending]);
};
