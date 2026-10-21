import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { useMemo } from "react";

import { getDashboardMetrics } from "../reporting/reportingService";
import type { AttentionCounters } from "./attentionDashboard";
import type { DashboardCandidate } from "./candidateDashboard";
import {
  buildKpiCards,
  type DashboardMetricsSnapshot,
  type KpiLeadRow,
} from "./kpiCards";

/**
 * Phone-first KPI strip for the dashboard hero area: four cards answering
 * "tốt hay xấu, đi hướng nào" in the first mobile viewport (pipeline headline,
 * new leads vs previous period, conversion trend, open conversations). Hidden
 * at ≥md, where the desktop dashboard keeps its existing worklist grid.
 */
const DASHBOARD_METRICS_QUERY_KEY = ["dashboard-metrics"] as const;

const EMPTY_CANDIDATES: readonly DashboardCandidate[] = [];

export const DashboardKpiCards = ({
  candidates = EMPTY_CANDIDATES,
  counters,
}: {
  candidates?: readonly DashboardCandidate[];
  counters?: AttentionCounters | null;
}) => {
  // Same TanStack contract as the queues: refetch quietly, never flash a
  // skeleton over populated cards.
  const { data: metrics } = useQuery<DashboardMetricsSnapshot>({
    queryKey: DASHBOARD_METRICS_QUERY_KEY,
    queryFn: () => getDashboardMetrics<DashboardMetricsSnapshot>(),
    refetchInterval: 60_000,
    staleTime: 30_000,
    gcTime: 5 * 60_000,
  });
  const rows = useMemo<KpiLeadRow[]>(
    () =>
      candidates.map((candidate) => ({
        created_at: candidate.created_at,
        lead_stage: candidate.lead?.lead_stage ?? null,
      })),
    [candidates],
  );
  const cards = useMemo(
    () => buildKpiCards({ metrics, counters, leads: rows }),
    [metrics, counters, rows],
  );

  return (
    <section className="dashboard-kpi-grid" aria-label="Chỉ số nhanh">
      {cards.map((card) => (
        <article
          key={card.id}
          className={`dashboard-kpi-card${
            card.emphasis === "headline" ? " dashboard-kpi-card--headline" : ""
          }`}
        >
          <h3 className="dashboard-kpi-label">{card.label}</h3>
          <p className="dashboard-kpi-value">{card.value}</p>
          {card.delta ? (
            <p
              className={`dashboard-kpi-delta dashboard-kpi-delta--${card.delta.tone}`}
            >
              <span className="dashboard-kpi-delta-figure">
                {card.delta.direction === "up" ? (
                  <ArrowUp aria-hidden="true" />
                ) : card.delta.direction === "down" ? (
                  <ArrowDown aria-hidden="true" />
                ) : (
                  <Minus aria-hidden="true" />
                )}
                {card.delta.text ?? "—"}
              </span>
              <span className="dashboard-kpi-delta-label">
                {card.delta.label}
              </span>
            </p>
          ) : null}
          {card.caption ? (
            <p className="dashboard-kpi-caption">{card.caption}</p>
          ) : null}
        </article>
      ))}
    </section>
  );
};
