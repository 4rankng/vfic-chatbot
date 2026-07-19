import { type ReactNode } from "react";
import { useDataProvider, useGetIdentity } from "ra-core";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowLeft, Bot } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { AlternateCard, PageHeading, PageShell } from "../kit";
import { cn } from "@/lib/utils";
import type { BotRunTraceDetail } from "../types";
import { durationLabel, formatDateTime, outcomeMeta } from "./botRunMeta";
import { DecisionTraceRenderer } from "./DecisionTracePanel";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { DECISION_TRACE_QUERY_KEY } from "./decisionTraceQueries";

const Field = ({ label, value }: { label: string; value?: ReactNode }) => (
  <div className="flex flex-col gap-1 border-b py-3 last:border-0">
    <span className="text-caption uppercase tracking-wide text-muted-foreground">
      {label}
    </span>
    <span className="text-body">{value ?? "—"}</span>
  </div>
);

const BotRunShowContent = ({ run }: { run: BotRunTraceDetail }) => {
  const meta = outcomeMeta(run.outcome);
  const dur = durationLabel(run);

  return (
    <AlternateCard className="mt-4" bodyClassName="overflow-hidden">
      <Card className="border-0 py-0">
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
            label="Cuộc trò chuyện"
            value={
              <span className="font-mono text-helper">
                {run.conversation_id}
              </span>
            }
          />
          <Field label="Kết quả" value={meta.label} />
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
          <div className="border-t py-4">
            <h3 className="text-section-title font-semibold text-foreground">
              Agent Thinking
            </h3>
            <p className="mt-1 text-helper leading-5 text-muted-foreground">
              Hiển thị nội dung suy luận mà nhà cung cấp mô hình trả về cho từng
              lượt, cùng các công cụ được mô hình chọn.
            </p>
            <div className="mt-3">
              <DecisionTraceRenderer trace={run.decision_trace} />
            </div>
          </div>
        </CardContent>
      </Card>
    </AlternateCard>
  );
};

export const BotRunShow = () => <BotRunShowPage />;

const BotRunShowPage = () => {
  const { id } = useParams();
  const runId = Number(id);
  const dataProvider = useDataProvider<CrmDataProvider>();
  const { identity } = useGetIdentity();
  const identityId = identity?.id ? String(identity.id) : "";
  const detailQuery = useQuery({
    queryKey: [...DECISION_TRACE_QUERY_KEY, identityId, "run", runId],
    queryFn: () => dataProvider.getBotRunTrace(runId),
    enabled: Boolean(identityId) && Number.isFinite(runId),
    gcTime: 0,
    staleTime: 0,
    retry: false,
  });

  return (
    <PageShell size="narrow">
      <PageHeading
        eyebrow="Kiểm tra vận hành"
        title="Chi tiết lần chạy bot"
        subtitle="Dữ liệu chẩn đoán nội bộ cho từng lượt xử lý."
        actions={
          <Button asChild variant="outline" size="sm">
            <Link to="/bot_runs">
              <ArrowLeft className="size-4" aria-hidden="true" />
              Quay lại
            </Link>
          </Button>
        }
      />
      {detailQuery.isPending ? (
        <div role="status" className="mt-4 p-4 text-body">
          Đang tải dấu vết…
        </div>
      ) : detailQuery.isError || !detailQuery.data ? (
        <div role="status" className="mt-4 p-4 text-body">
          Chưa tải được lần chạy bot. Hãy quay lại và thử lại.
        </div>
      ) : (
        <BotRunShowContent run={detailQuery.data} />
      )}
    </PageShell>
  );
};
