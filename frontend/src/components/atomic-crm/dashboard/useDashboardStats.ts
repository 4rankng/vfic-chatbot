import { useGetList } from "ra-core";
import { useMemo } from "react";
import type { Lead, Conversation } from "../types";
import { LEAD_STAGES } from "../types";

// KPI totals (qualified, hired, per-stage breakdown) all derive from this single
// page of leads, so the count must cover the full in-scope pipeline or the funnel
// undercounts silently. The expensive part was never the page size — it was the
// old per-render O(n × stages) .filter() chain, now replaced by the memoized
// single-pass aggregation below. Keep headroom at 1000.
const DASHBOARD_PER_PAGE = 1000;

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
  const { data: leads, isPending: isLeadsPending } = useGetList<Lead>("leads", {
    pagination: { page: 1, perPage: DASHBOARD_PER_PAGE },
  });

  const { data: conversations, isPending: isConversationsPending } =
    useGetList<Conversation>("conversations", {
      pagination: { page: 1, perPage: DASHBOARD_PER_PAGE },
    });

  return useMemo<DashboardStats>(() => {
    const leadList = leads ?? [];
    const conversationList = conversations ?? [];

    const totalLeads = leadList.length;

    // Single pass over leads: tally per-stage counts and the two scalar totals
    // (qualified, hired) the KPI cards need.
    const countsByStage = new Map<string, number>();
    let qualifiedCount = 0;
    let hiredCount = 0;

    for (const lead of leadList) {
      const stage = lead.lead_stage;
      countsByStage.set(stage, (countsByStage.get(stage) ?? 0) + 1);
      if (stage === "QUALIFIED") qualifiedCount += 1;
      else if (stage === "HIRED") hiredCount += 1;
    }

    // Unread = conversations in recruiter takeover (mode === "human"). Preserves
    // the original Dashboard "needs a human reply" heuristic; intentionally NOT
    // broadened to unread_count > 0 — that would silently change KPI semantics.
    let unreadConversationCount = 0;
    for (const conv of conversationList) {
      if (conv.mode === "human") {
        unreadConversationCount += 1;
      }
    }

    const hiredRate = totalLeads
      ? Math.round((hiredCount / totalLeads) * 100)
      : 0;

    const stageBreakdown: StageBreakdown[] = LEAD_STAGES.map((stage) => {
      const count = countsByStage.get(stage.value) ?? 0;
      const percentage = totalLeads
        ? Math.round((count / totalLeads) * 100)
        : 0;
      return {
        value: stage.value,
        label: stage.label,
        color: stage.color,
        count,
        percentage,
      };
    });

    return {
      totalLeads,
      qualifiedCount,
      unreadConversationCount,
      hiredRate,
      stageBreakdown,
      isPending: isLeadsPending || isConversationsPending,
    };
  }, [leads, conversations, isLeadsPending, isConversationsPending]);
};
