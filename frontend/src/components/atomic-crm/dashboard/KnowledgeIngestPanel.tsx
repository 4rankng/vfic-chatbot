import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock3,
  Database,
  Flame,
  Gauge,
  MessageCircle,
  Percent,
  Server,
  Send,
  TrendingUp,
  UserCheck,
  Users,
} from "lucide-react";
import { useNavigate, Navigate } from "react-router";
import { usePermissions } from "ra-core";
import { useDashboardStats } from "./useDashboardStats";
import { stageLabel } from "../knowledge/stageTone";

// ---------------------------------------------------------------------------
// Variant config — every visual delta between desktop and mobile lives here.
// Future viewports add a branch; business logic stays shared below.
// ---------------------------------------------------------------------------

type Variant = "desktop" | "mobile";

interface VariantConfig {
  /** Root wrapper element + classes */
  rootClass: string;
  /** Spinner container height */
  spinnerH: string;
  spinnerIcon: string;
  /** Card shell */
  cardClass: string;
  headerClass: string;
  titleSize: string;
  descSize: string;
  /** CardContent layout */
  contentClass: string;
  /** Metric grid rows */
  row1Grid: string;
  row2Grid: string;
  chatFunnelGrid: string;
  queueLabel: string;
  /** IngestMetric sizing */
  metricPad: string;
  metricHeaderGap: string;
  metricLabelSize: string;
  metricIconPad: string;
  metricIconSize: string;
  metricValueMargin: string;
  metricValueSize: string;
  /** StageRow sizing */
  stageRowPad: string;
  stageRowGap: string;
  stageLabelW: string;
  stageBarH: string;
  stageCountW: string;
  stageLabelSize: string;
  stageCountSize: string;
  /** Section + empty-state text sizes */
  sectionSize: string;
  emptySize: string;
  /** Issue card sizing */
  issueEmptyPad: string;
  issueEmptyTextClass: string;
  issueButtonPad: string;
  issueItemGap: string;
  issueFilenameSize: string;
  issueSubSize: string;
  issueStatusPad: string;
  issueErrorMargin: string;
  /** Subtitle format for issue cards */
  subtitleFn: (n: number) => string;
}

const V: Record<Variant, VariantConfig> = {
  desktop: {
    rootClass: "flex flex-col gap-6 mx-auto w-full pb-8",
    spinnerH: "h-[300px]",
    spinnerIcon: "w-8 h-8",
    cardClass: "bg-card",
    headerClass: "pb-4",
    titleSize: "text-xl",
    descSize: "text-xs",
    contentClass:
      "grid grid-cols-1 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)] gap-6",
    row1Grid: "grid grid-cols-2 lg:grid-cols-4 gap-3",
    row2Grid: "grid grid-cols-1 sm:grid-cols-3 gap-3",
    chatFunnelGrid: "grid grid-cols-2 lg:grid-cols-5 gap-3",
    queueLabel: "Queue ingest",
    metricPad: "px-3 py-3",
    metricHeaderGap: "gap-3",
    metricLabelSize: "text-xs",
    metricIconPad: "p-1.5",
    metricIconSize: "w-4 h-4",
    metricValueMargin: "mt-3",
    metricValueSize: "text-2xl",
    stageRowPad: "px-3 py-2",
    stageRowGap: "gap-3",
    stageLabelW: "w-36",
    stageBarH: "h-2",
    stageCountW: "w-10",
    stageLabelSize: "text-xs",
    stageCountSize: "text-sm",
    sectionSize: "text-xs",
    emptySize: "text-sm",
    issueEmptyPad: "px-4 py-5",
    issueEmptyTextClass: "text-sm",
    issueButtonPad: "px-3 py-3",
    issueItemGap: "gap-3",
    issueFilenameSize: "text-sm",
    issueSubSize: "text-xs",
    issueStatusPad: "px-2 py-1",
    issueErrorMargin: "mt-2",
    subtitleFn: (n) => `${n} phút chưa cập nhật`,
  },
  mobile: {
    rootClass: "mx-auto flex w-full max-w-screen-xl flex-col gap-5 px-4 py-5",
    spinnerH: "h-[200px]",
    spinnerIcon: "size-6",
    cardClass: "border border-border bg-card shadow-xs",
    headerClass: "pb-3 pt-4 px-4",
    titleSize: "text-base",
    descSize: "text-[11px]",
    contentClass: "px-4 pb-4 flex flex-col gap-4",
    row1Grid: "grid grid-cols-2 gap-3",
    row2Grid: "grid grid-cols-3 gap-2",
    chatFunnelGrid: "grid grid-cols-2 gap-3",
    queueLabel: "Queue",
    metricPad: "px-2.5 py-2",
    metricHeaderGap: "gap-2",
    metricLabelSize: "text-[9px]",
    metricIconPad: "p-1",
    metricIconSize: "size-3.5",
    metricValueMargin: "mt-2",
    metricValueSize: "text-lg",
    stageRowPad: "px-2.5 py-1.5",
    stageRowGap: "gap-2",
    stageLabelW: "w-28",
    stageBarH: "h-1.5",
    stageCountW: "w-8",
    stageLabelSize: "text-[10px]",
    stageCountSize: "text-xs",
    sectionSize: "text-[10px]",
    emptySize: "text-xs",
    issueEmptyPad: "px-3 py-4",
    issueEmptyTextClass: "text-xs",
    issueButtonPad: "px-2.5 py-2",
    issueItemGap: "gap-2",
    issueFilenameSize: "text-xs",
    issueSubSize: "text-[10px]",
    issueStatusPad: "px-1.5 py-0.5",
    issueErrorMargin: "mt-1",
    subtitleFn: (n) => `${n} phút`,
  },
} as const;

// ---------------------------------------------------------------------------
// Shared tone map — byte-identical in both original files
// ---------------------------------------------------------------------------

const TONE_CLASS = {
  ok: "text-emerald-600 bg-emerald-500/10 border-emerald-500/20",
  busy: "text-sky-600 bg-sky-500/10 border-sky-500/20",
  warn: "text-amber-600 bg-amber-500/10 border-amber-500/20",
  bad: "text-destructive bg-destructive/10 border-destructive/20",
  neutral: "text-muted-foreground bg-muted/30 border-border/70",
} as const;

type Tone = keyof typeof TONE_CLASS;

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const IngestMetric = ({
  label,
  value,
  icon,
  tone,
  v,
}: {
  label: string;
  value: React.ReactNode;
  icon: React.ReactNode;
  tone: Tone;
  v: VariantConfig;
}) => (
  <div
    className={`rounded-lg border border-border/60 bg-muted/20 ${v.metricPad}`}
  >
    <div className={`flex items-center justify-between ${v.metricHeaderGap}`}>
      <span
        className={`font-bold uppercase tracking-wider text-muted-foreground truncate ${v.metricLabelSize}`}
      >
        {label}
      </span>
      <span
        className={`rounded-md border ${v.metricIconPad} ${TONE_CLASS[tone]}`}
      >
        {icon}
      </span>
    </div>
    <div
      className={`${v.metricValueMargin} font-semibold font-mono tracking-tight text-foreground ${v.metricValueSize}`}
    >
      {value}
    </div>
  </div>
);

const formatPercent = (value: number) => `${Math.round(value)}%`;

const formatRate = (value: number) => `${Math.round(value * 100)}%`;

const formatSeconds = (value: number) => {
  if (value <= 0) return "0s";
  if (value < 60) return `${value.toFixed(value < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
};

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export const KnowledgeIngestPanel = ({ variant }: { variant: Variant }) => {
  const navigate = useNavigate();
  const { permissions } = usePermissions();
  const {
    avgBotResponseSeconds,
    botErrors,
    botRunCount,
    botSentCount,
    botSuccessRate,
    botSuppressedCount,
    botSuppressionRate,
    failedZaloSends,
    hiredRate,
    hotLeads,
    isPending,
    knowledgeIngest,
    openConversations,
    pendingFollowups,
    qualifiedCount,
    totalLeads,
    unreadConversationCount,
  } = useDashboardStats();
  const v = V[variant];

  if (permissions === "recruiter") {
    return <Navigate to="/leads" replace />;
  }

  return (
    <div className={v.rootClass}>
      {isPending ? (
        <div
          className={`w-full ${v.spinnerH} flex items-center justify-center text-muted-foreground`}
        >
          <Activity className={`${v.spinnerIcon} animate-spin`} />
        </div>
      ) : (
        <>
          <Card className={v.cardClass}>
            <CardHeader className={v.headerClass}>
              <CardTitle className="flex items-center gap-2">
                <span className="w-1.5 h-4.5 bg-primary rounded-full" />
                <span
                  className={`font-display ${v.titleSize} font-bold tracking-wider uppercase text-foreground`}
                >
                  Chatbot performance
                </span>
              </CardTitle>
              <CardDescription
                className={`${v.descSize} text-muted-foreground`}
              >
                Theo dõi bot có trả lời ổn định, bị chặn, lỗi gửi hay cần người
                tiếp quản
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className={v.row1Grid}>
                <IngestMetric
                  label="Bot runs"
                  value={botRunCount}
                  icon={<Bot className={v.metricIconSize} />}
                  tone="neutral"
                  v={v}
                />
                <IngestMetric
                  label="Đã gửi"
                  value={botSentCount}
                  icon={<Send className={v.metricIconSize} />}
                  tone={botSentCount > 0 ? "ok" : "neutral"}
                  v={v}
                />
                <IngestMetric
                  label="Tỷ lệ gửi"
                  value={formatPercent(botSuccessRate)}
                  icon={<Gauge className={v.metricIconSize} />}
                  tone={
                    botRunCount === 0
                      ? "neutral"
                      : botSuccessRate >= 85
                        ? "ok"
                        : botSuccessRate >= 65
                          ? "warn"
                          : "bad"
                  }
                  v={v}
                />
                <IngestMetric
                  label="TB phản hồi"
                  value={formatSeconds(avgBotResponseSeconds)}
                  icon={<Clock3 className={v.metricIconSize} />}
                  tone={
                    avgBotResponseSeconds === 0
                      ? "neutral"
                      : avgBotResponseSeconds <= 15
                        ? "ok"
                        : avgBotResponseSeconds <= 45
                          ? "warn"
                          : "bad"
                  }
                  v={v}
                />
              </div>

              <div className={v.row1Grid}>
                <IngestMetric
                  label="Bị chặn"
                  value={botSuppressedCount}
                  icon={<Percent className={v.metricIconSize} />}
                  tone={botSuppressedCount > 0 ? "warn" : "ok"}
                  v={v}
                />
                <IngestMetric
                  label="Tỷ lệ chặn"
                  value={formatRate(botSuppressionRate)}
                  icon={<AlertCircle className={v.metricIconSize} />}
                  tone={
                    botSuppressionRate === 0
                      ? "ok"
                      : botSuppressionRate <= 0.15
                        ? "neutral"
                        : botSuppressionRate <= 0.35
                          ? "warn"
                          : "bad"
                  }
                  v={v}
                />
                <IngestMetric
                  label="Bot errors"
                  value={botErrors}
                  icon={<AlertTriangle className={v.metricIconSize} />}
                  tone={botErrors > 0 ? "bad" : "ok"}
                  v={v}
                />
                <IngestMetric
                  label="Lỗi gửi Zalo"
                  value={failedZaloSends}
                  icon={<AlertCircle className={v.metricIconSize} />}
                  tone={failedZaloSends > 0 ? "bad" : "ok"}
                  v={v}
                />
              </div>

              <div className={v.chatFunnelGrid}>
                <IngestMetric
                  label="Cuộc mở"
                  value={openConversations}
                  icon={<MessageCircle className={v.metricIconSize} />}
                  tone="neutral"
                  v={v}
                />
                <IngestMetric
                  label="Human takeover"
                  value={unreadConversationCount}
                  icon={<UserCheck className={v.metricIconSize} />}
                  tone={unreadConversationCount > 0 ? "busy" : "ok"}
                  v={v}
                />
                <IngestMetric
                  label="Hot leads"
                  value={hotLeads}
                  icon={<Flame className={v.metricIconSize} />}
                  tone={hotLeads > 0 ? "busy" : "neutral"}
                  v={v}
                />
                <IngestMetric
                  label="Qualified"
                  value={`${qualifiedCount}/${totalLeads}`}
                  icon={<Users className={v.metricIconSize} />}
                  tone="neutral"
                  v={v}
                />
                <IngestMetric
                  label="Hired rate"
                  value={formatPercent(hiredRate)}
                  icon={<TrendingUp className={v.metricIconSize} />}
                  tone={hiredRate > 0 ? "ok" : "neutral"}
                  v={v}
                />
              </div>

              {pendingFollowups > 0 && (
                <div
                  className={`rounded-lg border border-border/60 bg-muted/20 ${v.metricPad} text-left ${v.emptySize} text-muted-foreground`}
                >
                  {pendingFollowups} follow-up đang chờ xử lý.
                </div>
              )}
            </CardContent>
          </Card>

          {knowledgeIngest ? (
            <Card className={v.cardClass}>
              <CardHeader className={v.headerClass}>
                <CardTitle className="flex items-center gap-2">
                  <span className="w-1.5 h-4.5 bg-primary rounded-full" />
                  <span
                    className={`font-display ${v.titleSize} font-bold tracking-wider uppercase text-foreground`}
                  >
                    Knowledge ingest
                  </span>
                </CardTitle>
                <CardDescription
                  className={`${v.descSize} text-muted-foreground`}
                >
                  Tín hiệu vận hành để quyết định retry, restart worker hoặc
                  kiểm tra LLM
                </CardDescription>
              </CardHeader>
              <CardContent className={v.contentClass}>
                {/* ---- Metrics section ---- */}
                <div className="space-y-5">
                  <div className={v.row1Grid}>
                    <IngestMetric
                      label="Đang xử lý"
                      value={knowledgeIngest.processing_count}
                      icon={<Activity className={v.metricIconSize} />}
                      tone={
                        knowledgeIngest.processing_count > 0 ? "busy" : "ok"
                      }
                      v={v}
                    />
                    <IngestMetric
                      label="Có thể kẹt"
                      value={knowledgeIngest.stuck_count}
                      icon={<Clock3 className={v.metricIconSize} />}
                      tone={knowledgeIngest.stuck_count > 0 ? "warn" : "ok"}
                      v={v}
                    />
                    <IngestMetric
                      label="Nguồn lỗi"
                      value={knowledgeIngest.failed_document_count}
                      icon={<AlertTriangle className={v.metricIconSize} />}
                      tone={
                        knowledgeIngest.failed_document_count > 0 ? "bad" : "ok"
                      }
                      v={v}
                    />
                    <IngestMetric
                      label="Đã xuất bản"
                      value={knowledgeIngest.published_document_count}
                      icon={<CheckCircle2 className={v.metricIconSize} />}
                      tone="ok"
                      v={v}
                    />
                  </div>

                  <div className={v.row2Grid}>
                    <IngestMetric
                      label={v.queueLabel}
                      value={knowledgeIngest.queue_depth}
                      icon={<Database className={v.metricIconSize} />}
                      tone={
                        knowledgeIngest.queue_depth > 0 ? "busy" : "neutral"
                      }
                      v={v}
                    />
                    <IngestMetric
                      label="RQ failed"
                      value={knowledgeIngest.failed_job_count}
                      icon={<AlertCircle className={v.metricIconSize} />}
                      tone={
                        knowledgeIngest.failed_job_count > 0
                          ? "warn"
                          : "neutral"
                      }
                      v={v}
                    />
                    <IngestMetric
                      label="Worker"
                      value={knowledgeIngest.worker_count}
                      icon={<Server className={v.metricIconSize} />}
                      tone={
                        knowledgeIngest.worker_count === 0 ? "bad" : "neutral"
                      }
                      v={v}
                    />
                  </div>

                  {/* ---- Stage breakdown ---- */}
                  <div className="space-y-3">
                    <div
                      className={`flex items-center justify-between ${v.sectionSize} font-bold uppercase tracking-wider text-muted-foreground`}
                    >
                      <span>Các bước xử lý</span>
                      <span>
                        {knowledgeIngest.stage_breakdown.length} trạng thái
                      </span>
                    </div>
                    <div className="space-y-2">
                      {knowledgeIngest.stage_breakdown.length === 0 ? (
                        <p className={`${v.emptySize} text-muted-foreground`}>
                          Chưa có nguồn kiến thức.
                        </p>
                      ) : (
                        knowledgeIngest.stage_breakdown.map((row) => (
                          <div
                            key={row.stage}
                            className={`flex items-center ${v.stageRowGap} rounded-lg bg-muted/20 ${v.stageRowPad}`}
                          >
                            <div
                              className={`${v.stageLabelW} ${v.stageLabelSize} font-semibold text-muted-foreground truncate`}
                            >
                              {stageLabel(row.stage)}
                            </div>
                            <div
                              className={`${v.stageBarH} flex-1 overflow-hidden rounded-full bg-muted/60`}
                            >
                              <div
                                className="h-full rounded-full bg-primary"
                                style={{
                                  width: `${Math.min(100, Math.max(8, row.count * 12))}%`,
                                }}
                              />
                            </div>
                            <div
                              className={`${v.stageCountW} text-right ${v.stageCountSize} font-semibold font-mono`}
                            >
                              {row.count}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>

                {/* ---- Recent issues ---- */}
                <div className="space-y-3">
                  <div
                    className={`flex items-center justify-between ${v.sectionSize} font-bold uppercase tracking-wider text-muted-foreground`}
                  >
                    <span>Vấn đề gần đây</span>
                    <button
                      type="button"
                      className="text-primary hover:text-primary/80"
                      onClick={() => navigate("/knowledge_sources")}
                    >
                      Mở kiến thức
                    </button>
                  </div>
                  {knowledgeIngest.recent_issues.length === 0 ? (
                    <div
                      className={`rounded-lg border border-border/60 bg-muted/25 ${v.issueEmptyPad} ${v.issueEmptyTextClass} text-muted-foreground`}
                    >
                      Không có nguồn lỗi hoặc đứng quá 10 phút.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {knowledgeIngest.recent_issues.map((issue) => (
                        <button
                          key={issue.id}
                          type="button"
                          className={`w-full rounded-lg border border-border/60 bg-muted/20 ${v.issueButtonPad} text-left transition-colors hover:bg-muted/45`}
                          onClick={() =>
                            navigate(`/knowledge_sources/${issue.id}/show`)
                          }
                        >
                          <div
                            className={`flex items-start justify-between ${v.issueItemGap}`}
                          >
                            <div className="min-w-0">
                              <p
                                className={`truncate ${v.issueFilenameSize} font-semibold text-foreground`}
                              >
                                {issue.file_name}
                              </p>
                              <p
                                className={`mt-0.5 ${v.issueSubSize} text-muted-foreground`}
                              >
                                {stageLabel(issue.stage)} ·{" "}
                                {v.subtitleFn(issue.minutes_since_update)}
                              </p>
                            </div>
                            <span
                              className={`shrink-0 rounded-md border border-border/70 ${v.issueStatusPad} text-[10px] font-bold uppercase tracking-wider text-muted-foreground`}
                            >
                              {issue.status}
                            </span>
                          </div>
                          {issue.error && (
                            <p
                              className={`${v.issueErrorMargin} line-clamp-2 text-xs text-destructive`}
                            >
                              {issue.error}
                            </p>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ) : null}
        </>
      )}
    </div>
  );
};
