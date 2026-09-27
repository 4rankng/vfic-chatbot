import type { ComponentType } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  TriangleAlert,
} from "lucide-react";

import type { Tone } from "../../reporting/domain/performanceDiagnostics";

/** Every status/metric surface in the dashboard renders a lucide glyph. */
export type Icon = ComponentType<{
  className?: string;
  "aria-hidden"?: boolean;
}>;

export const Status = ({
  tone,
  children,
}: {
  tone: Tone;
  children: string;
}) => {
  const StatusIcon =
    tone === "danger"
      ? AlertCircle
      : tone === "warning"
        ? TriangleAlert
        : tone === "success"
          ? CheckCircle2
          : Activity;
  return (
    <span className={`performance-status is-${tone}`}>
      <StatusIcon aria-hidden="true" />
      {children}
    </span>
  );
};

export const Metric = ({
  label,
  value,
  hint,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint: string;
  tone: Tone;
  icon: Icon;
}) => (
  <article className={`performance-metric is-${tone}`}>
    <div className="performance-metric-heading">
      <Icon aria-hidden={true} />
      <p>{label}</p>
    </div>
    <strong>{value}</strong>
    <small>{hint}</small>
  </article>
);
