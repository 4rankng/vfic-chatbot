import type { ComponentType } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  TriangleAlert,
} from "lucide-react";

import { BadgeWithIcon } from "@/components/base/badges/badges";

import type { Tone } from "../../reporting/domain/performanceDiagnostics";

/** Every status/metric surface in the dashboard renders a lucide glyph. */
export type Icon = ComponentType<{
  className?: string;
  "aria-hidden"?: boolean;
}>;

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
      iconLeading={StatusIcon}
    >
      {children}
    </BadgeWithIcon>
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
