import { Check, LoaderCircle, X } from "lucide-react";

import { cx } from "@/utils/cx";

import type {
  IngestCheckpoint,
  IngestCheckpointState,
} from "./ingest-timeline";

const MARKER_CLASS: Record<IngestCheckpointState, string> = {
  done: "bg-primary text-primary-foreground border-primary",
  active: "bg-background text-foreground border-border",
  pending: "bg-background text-muted-foreground border-border",
  failed: "bg-destructive text-white border-destructive",
};

const LABEL_CLASS: Record<IngestCheckpointState, string> = {
  done: "text-foreground",
  active: "text-foreground font-medium",
  pending: "text-muted-foreground",
  failed: "text-destructive",
};

const Marker = ({ state }: { state: IngestCheckpointState }) => (
  <span
    aria-hidden="true"
    className={cx(
      "relative z-10 flex size-6 shrink-0 items-center justify-center rounded-full border",
      MARKER_CLASS[state],
    )}
  >
    {state === "done" ? (
      <Check className="size-3.5" strokeWidth={2.5} />
    ) : state === "active" ? (
      <LoaderCircle className="size-3.5 animate-spin" />
    ) : state === "failed" ? (
      <X className="size-3.5" strokeWidth={2.5} />
    ) : null}
  </span>
);

export type IngestTimelineProps = Readonly<{
  checkpoints: readonly IngestCheckpoint[];
}>;

/**
 * Vertical checkpoint timeline for a brief ingest. A stage reads as done
 * only when the layer that owns it confirmed the work, so the recruiter
 * always sees which checkpoint the pipeline is waiting on.
 */
export const IngestTimeline = ({ checkpoints }: IngestTimelineProps) => (
  <ol
    role="status"
    aria-label="Tiến độ nạp kiến thức"
    className="project-ingest-timeline m-0 flex list-none flex-col p-0"
  >
    {checkpoints.map((checkpoint, index) => (
      <li key={checkpoint.key} className="relative flex gap-3 pb-4 last:pb-0">
        {index < checkpoints.length - 1 ? (
          <span
            aria-hidden="true"
            className={cx(
              "absolute top-6 left-3 h-[calc(100%-24px)] w-px",
              checkpoint.state === "done" ? "bg-primary" : "bg-border",
            )}
          />
        ) : null}
        <Marker state={checkpoint.state} />
        <div className="grid content-start gap-0.5 pt-0.5">
          <span className={cx("text-helper", LABEL_CLASS[checkpoint.state])}>
            {checkpoint.label}
          </span>
          {checkpoint.detail ? (
            <span className="text-helper text-muted-foreground">
              {checkpoint.detail}
            </span>
          ) : null}
        </div>
      </li>
    ))}
  </ol>
);
