import { type ReactNode } from "react";
import { useDataProvider, useGetIdentity, useTranslate } from "ra-core";
import { useQuery } from "@tanstack/react-query";
import { useHref, useParams } from "react-router";
import { ArrowLeft, Bot } from "lucide-react";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { PageHeading, PageShell } from "../kit";
import type { BotRunTraceDetail } from "../types";
import { durationLabel, formatDateTime, outcomeMeta } from "./botRunMeta";
import { DecisionTraceRenderer } from "./DecisionTracePanel";
import type { CrmDataProvider } from "../providers/rest/dataProvider";
import { DECISION_TRACE_QUERY_KEY } from "./decisionTraceQueries";
import "./bot-runs.css";

const Fact = ({ label, value }: { label: string; value?: ReactNode }) => (
  <div className="min-w-0 border-b border-[var(--workspace-border)] px-4 py-3 sm:odd:border-r">
    <dt className="text-caption uppercase tracking-wide text-muted-foreground">
      {label}
    </dt>
    <dd className="mt-1 break-words text-body">{value ?? "—"}</dd>
  </div>
);

export const BotRunShowContent = ({ run }: { run: BotRunTraceDetail }) => {
  const meta = outcomeMeta(run.outcome);
  const dur = durationLabel(run);

  return (
    <section className="bot-run-detail-panel">
      <header className="flex items-center justify-between gap-3 border-b border-[var(--workspace-border)] px-4 py-3">
        <h2 className="flex min-w-0 items-center gap-2 text-section-title font-semibold">
          <Bot className="size-4 text-muted-foreground" />
          Lần chạy bot #{run.id}
        </h2>
        {/* Untitled UI chip. `uu-scope` re-binds the four utility names this
            console and Untitled UI both define; see
            src/styles/untitledui-theme.css. */}
        <Badge
          className="uu-scope shrink-0 font-semibold"
          type="pill-color"
          size="sm"
          color={meta.badgeColor}
        >
          {meta.label}
        </Badge>
      </header>

      <dl className="grid sm:grid-cols-2">
        <Fact
          label="Cuộc trò chuyện"
          value={
            <span className="font-mono text-helper">{run.conversation_id}</span>
          }
        />
        <Fact label="Thời lượng" value={dur} />
        <Fact label="Bắt đầu" value={formatDateTime(run.started_at)} />
        <Fact
          label="Kết thúc"
          value={run.ended_at ? formatDateTime(run.ended_at) : null}
        />
      </dl>

      <div className="px-4 py-4">
        <h3 className="text-section-title font-semibold text-foreground">
          Dấu vết quyết định
        </h3>
        <p className="mt-1 text-helper leading-5 text-muted-foreground">
          Các bước suy luận và công cụ của lượt này.
        </p>
        <div className="mt-3">
          <DecisionTraceRenderer trace={run.decision_trace} />
        </div>
      </div>
    </section>
  );
};

export const BotRunShow = () => <BotRunShowPage />;

const BotRunShowPage = () => {
  const { id } = useParams();
  const runId = Number(id);
  const dataProvider = useDataProvider<CrmDataProvider>();
  const { identity } = useGetIdentity();
  const identityId = identity?.id ? String(identity.id) : "";
  const translate = useTranslate();
  const listHref = useHref("/bot_runs");
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
        className="uu-scope"
        eyebrow="Vận hành"
        title="Chi tiết lần chạy bot"
        subtitle="Kiểm tra dữ liệu chẩn đoán của lượt xử lý."
        actions={
          <Button
            href={listHref}
            color="secondary"
            size="sm"
            iconLeading={ArrowLeft}
          >
            Lần chạy bot
          </Button>
        }
      />
      {detailQuery.isPending ? (
        <div role="status" className="mt-4 p-4 text-body">
          Đang tải dấu vết…
        </div>
      ) : detailQuery.isError || !detailQuery.data ? (
        <div
          role="alert"
          className="mt-4 flex flex-wrap items-center justify-between gap-3 border-y border-[var(--workspace-border)] px-4 py-3 text-body"
        >
          <span>Chưa tải được lần chạy bot.</span>
          <Button
            type="button"
            color="secondary"
            size="sm"
            className="uu-scope"
            onClick={() => detailQuery.refetch()}
          >
            {translate("crm.common.retry")}
          </Button>
        </div>
      ) : (
        <BotRunShowContent run={detailQuery.data} />
      )}
    </PageShell>
  );
};
