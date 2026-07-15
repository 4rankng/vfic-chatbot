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
    <span className="text-caption uppercase tracking-wide text-muted-foreground">
      {label}
    </span>
    <span className="text-body">{value ?? "—"}</span>
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
          <CardTitle className="flex items-center gap-2 text-section-title">
            <Bot className="size-4 text-muted-foreground" />
            Lần chạy bot #{run.id}
          </CardTitle>
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2.5 py-0.5 text-helper font-semibold uppercase tracking-wide",
              meta.classes,
            )}
          >
            {meta.label}
          </span>
        </CardHeader>
        <CardContent className="flex flex-col px-4 py-2">
          <Field
            label="Câu trả lời đề xuất"
            value={
              run.proposed_reply ? (
                <pre className="whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-body">
                  {run.proposed_reply}
                </pre>
              ) : (
                "— không có —"
              )
            }
          />
          <Field
            label="Cuộc trò chuyện"
            value={
              <span className="font-mono text-helper">{run.conversation_id}</span>
            }
          />
          <Field label="Kết quả" value={meta.label} />
          <Field
            label="Phiên bản khi bắt đầu"
            value={
              <span>
                {run.version_at_start}{" "}
                <span className="text-helper text-muted-foreground">
                  (conversations.version khi lần chạy bắt đầu — dùng cho cơ chế
                  chống tranh chấp tiếp nhận)
                </span>
              </span>
            }
          />
          <Field label="Bắt đầu" value={formatDateTime(run.started_at)} />
          <Field
            label="Kết thúc"
            value={
              run.ended_at ? (
                <span>
                  {formatDateTime(run.ended_at)}
                  {dur ? (
                    <span className="text-helper text-muted-foreground">
                      {" "}
                      · thời lượng {dur}
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
      <h2 className="mr-auto text-content-title font-semibold">Lần chạy bot</h2>
    </TopToolbar>
    <BotRunShowContent />
  </ShowBase>
);
