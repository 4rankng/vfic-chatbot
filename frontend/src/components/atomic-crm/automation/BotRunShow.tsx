import { type ReactNode } from "react";
import { ShowBase, useRecordContext } from "ra-core";
import { TopToolbar } from "../layout/TopToolbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Bot } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BotRun } from "../types";
import { durationLabel, formatDateTime, outcomeMeta } from "./botRunMeta";

const Field = ({ label, value }: { label: string; value?: ReactNode }) => (
  <div className="flex flex-col gap-1 border-b py-3 last:border-0">
    <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
      {label}
    </span>
    <span className="text-sm">{value ?? "—"}</span>
  </div>
);

const BotRunShowContent = () => {
  const run = useRecordContext<BotRun>();
  if (!run) return null;
  const meta = outcomeMeta(run.outcome);
  const dur = durationLabel(run);

  return (
    <div className="mx-auto mt-4 max-w-3xl">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 border-b px-4 py-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Bot className="size-4 text-muted-foreground" />
            Bot Run #{run.id}
          </CardTitle>
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide",
              meta.classes,
            )}
          >
            {meta.label}
          </span>
        </CardHeader>
        <CardContent className="flex flex-col px-4 py-2">
          <Field
            label="Proposed reply"
            value={
              run.proposed_reply ? (
                <pre className="whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-sm">
                  {run.proposed_reply}
                </pre>
              ) : (
                "— none —"
              )
            }
          />
          <Field
            label="Conversation"
            value={
              <span className="font-mono text-xs">{run.conversation_id}</span>
            }
          />
          <Field label="Outcome" value={run.outcome} />
          <Field
            label="Version at start"
            value={
              <span>
                {run.version_at_start}{" "}
                <span className="text-xs text-muted-foreground">
                  (conversations.version when the run began — used by the
                  takeover race guard)
                </span>
              </span>
            }
          />
          <Field label="Started" value={formatDateTime(run.started_at)} />
          <Field
            label="Ended"
            value={
              run.ended_at ? (
                <span>
                  {formatDateTime(run.ended_at)}
                  {dur ? (
                    <span className="text-xs text-muted-foreground">
                      {" "}
                      · duration {dur}
                    </span>
                  ) : null}
                </span>
              ) : null
            }
          />
        </CardContent>
      </Card>
    </div>
  );
};

export const BotRunShow = () => (
  <ShowBase>
    <TopToolbar>
      <h2 className="mr-auto text-xl font-semibold">Bot Run</h2>
    </TopToolbar>
    <BotRunShowContent />
  </ShowBase>
);
