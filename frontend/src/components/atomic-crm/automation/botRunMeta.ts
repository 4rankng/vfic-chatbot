import type { BotRun } from "../types";

// Outcome = the takeover race-guard verdict (bot_runs.outcome CHECK).
// sent      → delivered to Zalo
// suppressed → a recruiter took over mid-run (version mismatch) — NOT sent
// error     → the run failed
export type OutcomeBadgeColor = "success" | "warning" | "error";

export const OUTCOME_META: Record<
  BotRun["outcome"],
  {
    label: string;
    /** Untitled UI `Badge` colour for the outcome chip (`BotRunShow`). */
    badgeColor: OutcomeBadgeColor;
    indicatorClasses: string;
  }
> = {
  sent: {
    label: "Đã gửi",
    badgeColor: "success",
    indicatorClasses: "text-success",
  },
  suppressed: {
    label: "Đã chặn",
    badgeColor: "warning",
    // `text-warning-foreground` is white — it is the ink for a filled warning
    // surface, not for a bare label on the cream card. The row paints the
    // marker and the label with `currentColor` on paper, so it has to be the
    // amber ink, like its `sent`/`error` siblings.
    indicatorClasses: "text-warning",
  },
  error: {
    label: "Lỗi",
    badgeColor: "error",
    indicatorClasses: "text-destructive",
  },
};

export const outcomeMeta = (
  outcome: string,
): { label: string; badgeColor: OutcomeBadgeColor; indicatorClasses: string } =>
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
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} giây`;
  return `${Math.round(ms / 60_000)} phút`;
};

export const formatDateTime = (iso?: string | null): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(d);
};
