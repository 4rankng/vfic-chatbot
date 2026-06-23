import { useMemo, type ReactNode } from "react";
import { useListContext } from "ra-core";
import { cn } from "@/lib/utils";

import { LEAD_STAGES } from "../types";
import { getLeadsByStage } from "./stages";

/**
 * Pill-chip stage breakdown. Clicking a chip filters the list to that stage
 * (?lead_stage=). The total chip uses the server `total`; per-stage chips are
 * derived from the currently-loaded data slice via getLeadsByStage — so when
 * total > loaded slice the per-stage counts reflect only the loaded leads.
 */
export const LeadsSummaryHeader = () => {
  const { data, total, filterValues, setFilters } = useListContext();
  const filters = filterValues ?? {};
  const activeStage = filters.lead_stage as string | undefined;

  const byStage = useMemo(
    () => getLeadsByStage(data ?? [], LEAD_STAGES),
    [data],
  );

  const setStage = (value?: string) => {
    const next = { ...filters };
    delete next.lead_stage;
    setFilters(value ? { ...next, lead_stage: value } : next);
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <SummaryChip active={!activeStage} onClick={() => setStage(undefined)}>
        Tổng <Count>{total ?? 0}</Count>
      </SummaryChip>
      {LEAD_STAGES.map((s) => (
        <SummaryChip
          key={s.value}
          active={activeStage === s.value}
          onClick={() => setStage(s.value)}
        >
          {s.label} <Count>{byStage[s.value]?.length ?? 0}</Count>
        </SummaryChip>
      ))}
    </div>
  );
};

const SummaryChip = ({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) => (
  <button
    type="button"
    onClick={onClick}
    className={cn(
      "inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors",
      active
        ? "border border-primary/40 bg-primary/10 text-primary"
        : "border border-transparent bg-muted text-muted-foreground hover:bg-accent hover:text-foreground",
    )}
  >
    {children}
  </button>
);

const Count = ({ children }: { children: ReactNode }) => (
  <span className="rounded-full bg-background/80 px-1.5 text-[11px] font-semibold tabular-nums">
    {children}
  </span>
);
