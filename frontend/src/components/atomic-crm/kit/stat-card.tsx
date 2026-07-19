import type { ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Statistic card with metric, delta badge, and optional sparkline.
 *
 * Adapted from Tailkit `a-c-statistics-11` (Simple with Charts). The sparkline
 * is an inline SVG — pass a `series` of numbers and the path is generated
 * deterministically (no chart dependency).
 *
 * Tone conventions:
 *   - delta > 0  → emerald up-arrow
 *   - delta < 0  → rose down-arrow
 *   - delta === 0 or undefined → muted neutral dash
 *
 * Consume via `--tt-*` tokens.
 */
type StatCardTone = "neutral" | "success" | "warning" | "danger";

type StatCardProps = {
  /** Numeric value or formatted string ("3.76%", "142", "6m 2s"). */
  value: ReactNode;
  /** Label under the value ("Tỷ lệ chuyển đổi", "Hồ sơ tuần này"). */
  label: ReactNode;
  /** Optional hint under the label ("from 12 products"). */
  hint?: ReactNode;
  /** Signed percentage for the delta badge. Positive = up, negative = down. */
  deltaPct?: number;
  /** Override the tone derived from deltaPct sign. */
  tone?: StatCardTone;
  /** Number series for the sparkline (any length ≥ 2). */
  series?: ReadonlyArray<number>;
  className?: string;
  /** Optional icon rendered at the top-left of the value block. */
  icon?: ReactNode;
  /** Right-aligned action slot (e.g. a "⋯" menu button). */
  action?: ReactNode;
};

const TONE_DELTA_UP: Record<StatCardTone, string> = {
  neutral: "text-[var(--tt-ink-muted)]",
  success: "text-emerald-600 dark:text-emerald-400",
  warning: "text-amber-600 dark:text-amber-400",
  danger: "text-rose-600 dark:text-rose-400",
};

/**
 * Build a smoothable sparkline path from a numeric series. Maps the series
 * into a 0..1 × 0..1 box then emits an SVG path string. Caller is responsible
 * for sizing via viewBox (we use 2000×1000 to match Tailkit's anatomy).
 */
function buildSparklinePath(series: ReadonlyArray<number>): {
  area: string;
  line: string;
} | null {
  if (series.length < 2) return null;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = max - min || 1;
  const W = 2000;
  const H = 1000;
  const padY = H * 0.1;
  const usableH = H - padY * 2;
  const stepX = W / (series.length - 1);
  const points = series.map((v, i) => {
    const x = i * stepX;
    const y = H - padY - ((v - min) / range) * usableH;
    return [x, y] as const;
  });
  const line = points
    .map(
      ([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`,
    )
    .join(" ");
  const area = `${line} L ${W} ${H} L 0 ${H} Z`;
  return { area, line };
}

export function StatCard({
  value,
  label,
  hint,
  deltaPct,
  tone,
  series,
  className,
  icon,
  action,
}: StatCardProps) {
  const derivedTone: StatCardTone =
    tone ??
    (deltaPct === undefined
      ? "neutral"
      : deltaPct > 0
        ? "success"
        : deltaPct < 0
          ? "danger"
          : "neutral");
  const sparkline = series ? buildSparklinePath(series) : null;
  const DeltaIcon =
    deltaPct === undefined
      ? Minus
      : deltaPct > 0
        ? ArrowUpRight
        : deltaPct < 0
          ? ArrowDownRight
          : Minus;
  const showDelta = deltaPct !== undefined;

  return (
    <div
      className={cn(
        "tt-stat-card group relative flex items-center justify-between gap-3 rounded-lg border border-[var(--tt-border)] bg-[var(--tt-surface-lift)] p-5 shadow-[var(--tt-shadow-xs)]",
        className,
      )}
    >
      <div className="tt-stat-card-body min-w-0 grow">
        {showDelta ? (
          <div
            className={cn(
              "tt-stat-card-delta mb-1 flex items-center gap-0.5 text-[length:var(--text-meta)] font-semibold",
              TONE_DELTA_UP[derivedTone],
            )}
          >
            <span>
              {deltaPct! > 0 ? "+" : ""}
              {deltaPct!.toFixed(1)}%
            </span>
            <DeltaIcon className="size-4" aria-hidden="true" />
          </div>
        ) : null}
        <dl className="tt-stat-card-metric">
          <dt className="text-[length:var(--text-metric)] font-extrabold leading-none text-[var(--tt-ink)]">
            {value}
          </dt>
          <dd className="mt-1 flex items-center gap-1.5 text-[length:var(--text-meta)] font-medium text-[var(--tt-ink-muted)]">
            {icon ? (
              <span className="text-[var(--tt-ink-muted)]" aria-hidden="true">
                {icon}
              </span>
            ) : null}
            <span>{label}</span>
          </dd>
          {hint ? (
            <dd className="mt-0.5 text-[length:var(--text-caption)] text-[var(--tt-ink-faint)]">
              {hint}
            </dd>
          ) : null}
        </dl>
      </div>
      {sparkline ? (
        <div
          className="tt-stat-card-spark relative w-full max-w-28 shrink-0"
          aria-hidden="true"
        >
          <div className="absolute inset-0 bg-linear-to-t from-[var(--tt-surface-lift)] via-transparent to-transparent" />
          <svg
            viewBox="0 0 2000 1000"
            preserveAspectRatio="none"
            className="h-12 w-full"
          >
            <path d={sparkline.area} fill="var(--tt-accent)" opacity={0.1} />
            <path
              d={sparkline.line}
              fill="none"
              stroke="var(--tt-accent)"
              strokeWidth={30}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          </svg>
        </div>
      ) : null}
      {action ? (
        <div className="tt-stat-card-action absolute right-3 top-3">
          {action}
        </div>
      ) : null}
    </div>
  );
}

export default StatCard;
