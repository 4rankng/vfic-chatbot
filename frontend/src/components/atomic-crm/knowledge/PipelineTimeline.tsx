import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { KnowledgeSource } from "../types";
import {
  PIPELINE_STEPS,
  isFailed,
  isPublished,
  pipelineStepCopy,
  pipelineStepIndex,
} from "./knowledgePipelineUtils";
export const PipelineTimeline = ({ source }: { source: KnowledgeSource }) => {
  const currentIndex = pipelineStepIndex(source);

  return (
    <ol className="grid gap-2">
      {PIPELINE_STEPS.map((step, index) => {
        const copy = pipelineStepCopy(source, step);
        const done = isPublished(source) || index < currentIndex;
        const current = !isPublished(source) && index === currentIndex;
        const failedHere = isFailed(source) && index === currentIndex;

        return (
          <li
            key={step.key}
            className={cn(
              "grid grid-cols-[28px_minmax(0,1fr)] gap-3 rounded-[10px] p-2",
              current && !failedHere && "bg-[var(--kb-teal-soft)]",
              failedHere && "bg-[var(--kb-rust-soft)]",
            )}
          >
            <span
              className={cn(
                "mt-0.5 flex size-7 items-center justify-center rounded-full",
                done && "bg-[var(--kb-teal)] text-[var(--kb-teal-soft)]",
                current &&
                  !failedHere &&
                  "bg-[var(--kb-teal)] text-[var(--kb-teal-soft)]",
                failedHere && "bg-[var(--kb-rust)] text-white",
                !done &&
                  !current &&
                  !failedHere &&
                  "bg-secondary text-muted-foreground",
              )}
            >
              {failedHere ? (
                <AlertTriangle className="size-4" />
              ) : done ? (
                <CheckCircle2 className="size-4" />
              ) : current ? (
                <Activity className="size-4" />
              ) : (
                <CircleDashed className="size-4" />
              )}
            </span>
            <span className="min-w-0">
              <span className="block text-body font-semibold text-foreground">
                {copy.label}
              </span>
              <span className="mt-0.5 block break-words text-helper leading-5 text-muted-foreground">
                {copy.description}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
};
