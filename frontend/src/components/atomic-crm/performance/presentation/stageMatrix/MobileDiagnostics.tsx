import { useState } from "react";
import { ChevronDown } from "lucide-react";

import {
  STAGE_LABELS,
  STAGE_TARGETS,
  formatMetricDuration as fmtMs,
} from "../../../reporting/domain/performanceDiagnostics";
import type { PerfMetrics } from "../../usePerformanceStats";

/**
 * Narrow-screen twin of the stage matrix: the same candidate/internal stage
 * groups, collapsed behind one disclosure per group.
 */
export const MobileDiagnostics = ({
  candidate,
  internal,
  percentiles,
}: {
  candidate: string[];
  internal: string[];
  percentiles: PerfMetrics["percentiles"];
}) => {
  const [openGroup, setOpenGroup] = useState<"pipeline" | "llm" | null>(
    "pipeline",
  );
  const groups = [
    { id: "pipeline" as const, label: "Pipeline", rows: candidate },
    { id: "llm" as const, label: "LLM & dữ liệu", rows: internal },
  ];

  return (
    <div className="performance-mobile-diagnostics">
      {groups
        .filter((group) => group.rows.length > 0)
        .map((group) => {
          const open = openGroup === group.id;
          return (
            <section key={group.id} className="performance-diagnostic-group">
              <button
                type="button"
                aria-expanded={open}
                onClick={() => setOpenGroup(open ? null : group.id)}
              >
                <span>{group.label}</span>
                <ChevronDown aria-hidden="true" />
              </button>
              {open ? (
                <div className="performance-diagnostic-rows">
                  {group.rows.map((key) => {
                    const stage = percentiles[key];
                    return (
                      <div key={key}>
                        <span>{STAGE_LABELS[key]}</span>
                        <strong>{fmtMs(stage?.p95)}</strong>
                        <small>
                          {STAGE_TARGETS[key] == null
                            ? "Không có mục tiêu"
                            : `Mục tiêu ≤ ${fmtMs(STAGE_TARGETS[key])}`}
                        </small>
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </section>
          );
        })}
    </div>
  );
};
