import type { ComponentType } from "react";
import { AlertCircle, AlertTriangle, CheckCircle } from "@untitledui/icons";

import { BadgeWithIcon } from "@/components/base/badges/badges";
import { ProgressBarBase } from "@/components/base/progress-indicators/progress-indicators";

import type { Tone } from "../../reporting/domain/performanceDiagnostics";

/** Every status/metric surface in the dashboard renders an Untitled UI glyph. */
export type Icon = ComponentType<{
  className?: string;
  "aria-hidden"?: boolean;
}>;

const STATUS_ICONS = {
  danger: AlertCircle,
  warning: AlertTriangle,
  success: CheckCircle,
  neutral: CheckCircle,
} as const;

/**
 * Tone chip on Untitled UI's `BadgeWithIcon`. `uu-scope` rides the badge
 * because the library and this console both define `bg-primary` /
 * `bg-secondary` / `text-primary` / `border-primary`; outside it the chip would
 * paint with the console's meaning. See `src/styles/untitledui-theme.css`.
 */
export const Status = ({
  tone,
  children,
}: {
  tone: Tone;
  children: string;
}) => (
  <BadgeWithIcon
    type="pill-color"
    size="md"
    color={
      tone === "danger"
        ? "error"
        : tone === "warning"
          ? "warning"
          : tone === "success"
            ? "success"
            : "gray"
    }
    className="uu-scope"
    iconLeading={STATUS_ICONS[tone]}
  >
    {children}
  </BadgeWithIcon>
);

/**
 * Quiet severity marker for table rows: a tone dot plus the word, instead of a
 * full badge per row — the rows already carry an outcome badge, and two pill
 * chips per row is noise.
 */
export const Severity = ({ tone }: { tone: Tone }) => (
  <span className={`performance-severity is-${tone}`}>
    <i aria-hidden="true" />
    {tone === "danger" ? "Cao" : tone === "warning" ? "Trung bình" : "Thấp"}
  </span>
);

export const Metric = ({
  label,
  value,
  hint,
  tone,
  icon: Icon,
  meter,
}: {
  label: string;
  value: string;
  hint: string;
  tone: Tone;
  icon: Icon;
  /** Optional 0–100 saturation meter under the value. */
  meter?: number;
}) => (
  <article className={`performance-metric is-${tone}`}>
    <div className="performance-metric-heading">
      <Icon aria-hidden={true} />
      <p>{label}</p>
    </div>
    <strong>{value}</strong>
    <small>{hint}</small>
    {meter != null ? (
      // The value and hint above already carry the reading; the meter is the
      // visual echo, so it stays out of the accessibility tree.
      <span aria-hidden="true" className="uu-scope">
        <ProgressBarBase
          value={Math.min(100, Math.max(0, meter))}
          className="performance-metric-meter"
          progressClassName={`performance-metric-meter-fill is-${tone}`}
        />
      </span>
    ) : null}
  </article>
);
