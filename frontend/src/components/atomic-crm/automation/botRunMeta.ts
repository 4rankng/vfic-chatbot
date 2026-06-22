import type { BotRun } from "../types";

// Outcome = the takeover race-guard verdict (bot_runs.outcome CHECK).
// sent      → delivered to Zalo
// suppressed → a recruiter took over mid-run (version mismatch) — NOT sent
// error     → the run failed
export const OUTCOME_META: Record<
  BotRun["outcome"],
  { label: string; classes: string }
> = {
  sent: { label: "Sent", classes: "bg-emerald-500 text-white" },
  suppressed: {
    label: "Suppressed",
    classes: "bg-amber-500 text-white",
  },
  error: { label: "Error", classes: "bg-rose-500 text-white" },
};

export const outcomeMeta = (
  outcome: string,
): { label: string; classes: string } =>
  OUTCOME_META[outcome as BotRun["outcome"]] ?? OUTCOME_META.error;

/** Run wall-clock duration (ended_at − started_at), or null if not finished. */
export const durationLabel = (run: {
  started_at: string;
  ended_at: string | null;
}): string | null => {
  if (!run.ended_at || !run.started_at) return null;
  const ms =
    new Date(run.ended_at).getTime() - new Date(run.started_at).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms / 60_000)} m`;
};

export const formatDateTime = (iso?: string | null): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(d);
};
