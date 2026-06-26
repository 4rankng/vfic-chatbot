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
  total_leads: number;
  qualified_count: number;
  hired_count: number;
  hired_rate: number;
  unread_conversation_count: number;
  stage_breakdown: StageBreakdownItem[];
}

export interface StageBreakdown {
  value: string;
  label: string;
  color: string;
  count: number;
  percentage: number;
}

export interface DashboardStats {
  totalLeads: number;
  qualifiedCount: number;
  unreadConversationCount: number;
  hiredRate: number;
  stageBreakdown: StageBreakdown[];
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
        totalLeads: 0,
        qualifiedCount: 0,
        unreadConversationCount: 0,
        hiredRate: 0,
        stageBreakdown: [],
        isPending,
      };
    }
    // Merge the server's value+count+percentage into the canonical LEAD_STAGES
    // order/label/color so the funnel renders consistently even for zero-count
    // stages (which the backend emits too).
    const byValue = new Map(data.stage_breakdown.map((s) => [s.value, s]));
    return {
      totalLeads: data.total_leads,
      qualifiedCount: data.qualified_count,
      unreadConversationCount: data.unread_conversation_count,
      hiredRate: data.hired_rate,
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
