import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
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
  MessageCircle,
  Send,
  Server,
  Timer,
} from "lucide-react";
import { Navigate, useNavigate } from "react-router";
import { usePermissions } from "ra-core";
import { useDashboardStats } from "./useDashboardStats";
import { stageLabel } from "../knowledge/stageTone";

type Variant = "desktop" | "mobile";

type Tone = "ok" | "busy" | "warn" | "bad" | "neutral";

interface VariantConfig {
  rootClass: string;
  cardClass: string;
  headerClass: string;
  contentClass: string;
  spinnerClass: string;
  titleClass: string;
  descriptionClass: string;
  issueSubtitle: (minutes: number) => string;
}

const V: Record<Variant, VariantConfig> = {
  desktop: {
    rootClass: "dashboard-ops-stack mx-auto flex w-full flex-col gap-5 pb-8",
    cardClass: "bg-card/85",
    headerClass: "pb-3",
    contentClass: "px-5 pb-5",
    spinnerClass: "h-[300px]",
    titleClass: "text-xl",
    descriptionClass: "text-xs",
    issueSubtitle: (minutes) => `${minutes} phút chưa cập nhật`,
  },
  mobile: {
    rootClass: "mx-auto flex w-full flex-col gap-4 px-4 py-5 pb-28",
    cardClass: "border border-border bg-card shadow-xs",
    headerClass: "px-4 pb-3 pt-4",
    contentClass: "px-4 pb-4",
    spinnerClass: "h-[220px]",
    titleClass: "text-base",
    descriptionClass: "text-[11px]",
    issueSubtitle: (minutes) => `${minutes} phút`,
  },
};

const TONE_CLASS: Record<Tone, string> = {
  ok: "text-emerald-600 bg-emerald-500/10 border-emerald-500/20",
  busy: "text-sky-600 bg-sky-500/10 border-sky-500/20",
  warn: "text-amber-600 bg-amber-500/10 border-amber-500/20",
  bad: "text-destructive bg-destructive/10 border-destructive/20",
  neutral: "text-muted-foreground bg-muted/35 border-border/70",
};

const BAR_CLASS: Record<Tone, string> = {
  ok: "bg-emerald-500",
  busy: "bg-sky-500",
  warn: "bg-amber-500",
  bad: "bg-destructive",
  neutral: "bg-muted-foreground",
};

const DONUT_COLOR: Record<Tone, string> = {
  ok: "oklch(0.6222 0.1338 155.6)",
  busy: "oklch(0.72 0.14 74)",
  warn: "oklch(0.72 0.14 74)",
  bad: "var(--destructive)",
  neutral: "var(--primary)",
};

const clamp = (value: number, min = 0, max = 100) =>
  Math.min(max, Math.max(min, value));

const formatPercent = (value: number) => `${Math.round(value)}%`;

const formatRate = (value: number) => `${Math.round(value * 100)}%`;

const formatSeconds = (value: number) => {
  if (value <= 0) return "0s";
  if (value < 60) return `${value.toFixed(value < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
};

const panelTitle = (
  title: string,
  subtitle: string,
  icon: React.ReactNode,
  v: VariantConfig,
) => (
  <CardHeader className={v.headerClass}>
    <CardTitle className="flex items-center gap-2">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-border/70 bg-muted/30 text-primary">
        {icon}
      </span>
      <span
        className={`font-display ${v.titleClass} font-bold uppercase tracking-wider text-foreground`}
      >
        {title}
      </span>
    </CardTitle>
    <CardDescription className={`${v.descriptionClass} text-muted-foreground`}>
      {subtitle}
    </CardDescription>
  </CardHeader>
);

const CompactMetric = ({
  label,
  value,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: React.ReactNode;
  icon: React.ReactNode;
  tone?: Tone;
}) => (
  <div className="min-w-0 rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5">
    <div className="flex items-start justify-between gap-2">
      <span className="min-w-0 text-[11px] font-bold uppercase leading-snug tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className={`shrink-0 rounded-md border p-1 ${TONE_CLASS[tone]}`}>
        {icon}
      </span>
    </div>
    <div className="mt-2 font-mono text-xl font-semibold tracking-tight text-foreground">
      {value}
    </div>
  </div>
);

const ProgressRow = ({
  label,
  value,
  percent,
  tone = "neutral",
  detail,
}: {
  label: string;
  value: React.ReactNode;
  percent: number;
  tone?: Tone;
  detail?: string;
}) => (
  <div className="space-y-1.5">
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="min-w-0 truncate font-semibold text-muted-foreground">
        {label}
      </span>
      <span className="shrink-0 font-mono font-semibold text-foreground">
        {value}
      </span>
    </div>
    <div className="h-2 overflow-hidden rounded-full bg-muted/70">
      <div
        className={`h-full rounded-full ${BAR_CLASS[tone]}`}
        style={{ width: `${clamp(percent)}%` }}
      />
    </div>
    {detail ? (
      <p className="text-[11px] text-muted-foreground">{detail}</p>
    ) : null}
  </div>
);

const DonutMetric = ({
  value,
  label,
  caption,
  tone,
}: {
  value: number;
  label: string;
  caption: string;
  tone: Tone;
}) => {
  const percent = clamp(value);
  const color = DONUT_COLOR[tone];

  return (
    <div className="flex items-center gap-4">
      <div
        className="grid size-28 shrink-0 place-items-center rounded-full"
        style={{
          background: `conic-gradient(${color} ${percent}%, color-mix(in oklab, var(--muted) 74%, var(--background)) 0)`,
        }}
        role="img"
        aria-label={`${label}: ${formatPercent(percent)}`}
      >
        <div className="grid size-[82px] place-items-center rounded-full bg-card text-center">
          <span className="font-mono text-2xl font-semibold tracking-tight">
            {formatPercent(percent)}
          </span>
        </div>
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-foreground">{label}</p>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          {caption}
        </p>
      </div>
    </div>
  );
};

const DashboardCommandHeader = ({
  openConversations,
  hotLeads,
  pendingFollowups,
  activeTurns,
}: {
  openConversations: number;
  hotLeads: number;
  pendingFollowups: number;
  activeTurns: number;
}) => (
  <header className="ops-command-header dashboard-command-header">
    <div className="ops-command-title">
      <div className="ops-command-mark">
        <Activity className="size-5" />
      </div>
      <div className="min-w-0">
        <p className="ops-kicker">Trung tâm vận hành</p>
        <h1>Tổng quan</h1>
        <p>
          Theo dõi sức khỏe chatbot, hội thoại cần xử lý và quy trình huấn
          luyện kiến thức trong một màn hình vận hành.
        </p>
      </div>
    </div>
    <div className="dashboard-live-card" aria-label="Tín hiệu đang hoạt động">
      <span>
        <MessageCircle className="size-3.5" />
        {openConversations} hội thoại mở
      </span>
      <span>
        <Flame className="size-3.5" />
        {hotLeads} lead nóng
      </span>
      <span>
        <Timer className="size-3.5" />
        {activeTurns + pendingFollowups} cần theo dõi
      </span>
    </div>
  </header>
);

const DashboardStatusStrip = ({
  totalLeads,
  unreadConversationCount,
  pendingFollowups,
  turnsLast5min,
  p95BotResponseSeconds,
  webhookQueueDepth,
}: {
  totalLeads: number;
  unreadConversationCount: number;
  pendingFollowups: number;
  turnsLast5min: number;
  p95BotResponseSeconds: number;
  webhookQueueDepth: number;
}) => (
  <section className="ops-status-strip dashboard-status-strip">
    <div>
      <span className="ops-status-label">Ứng viên</span>
      <strong>{totalLeads}</strong>
      <small>Tổng hồ sơ</small>
    </div>
    <div>
      <span className="ops-status-label">Chưa đọc</span>
      <strong>{unreadConversationCount}</strong>
      <small>Hội thoại cần xem</small>
    </div>
    <div>
      <span className="ops-status-label">Cần hẹn lại</span>
      <strong>{pendingFollowups}</strong>
      <small>Đang chờ xử lý</small>
    </div>
    <div>
      <span className="ops-status-label">5 phút gần nhất</span>
      <strong>{turnsLast5min}</strong>
      <small>Lượt chatbot</small>
    </div>
    <div>
      <span className="ops-status-label">P95 / Hàng đợi</span>
      <strong>{formatSeconds(p95BotResponseSeconds)}</strong>
      <small>{webhookQueueDepth} webhook đang chờ</small>
    </div>
  </section>
);

const ChatbotHealthCard = ({
  v,
  botRunCount,
  botSentCount,
  botSuccessRate,
  avgBotResponseSeconds,
  botErrors,
  failedZaloSends,
}: {
  v: VariantConfig;
  botRunCount: number;
  botSentCount: number;
  botSuccessRate: number;
  avgBotResponseSeconds: number;
  botErrors: number;
  failedZaloSends: number;
}) => {
  const successTone: Tone =
    botRunCount === 0
      ? "neutral"
      : botSuccessRate >= 85
        ? "ok"
        : botSuccessRate >= 65
          ? "warn"
          : "bad";
  const latencyTone: Tone =
    avgBotResponseSeconds === 0
      ? "neutral"
      : avgBotResponseSeconds <= 15
        ? "ok"
        : avgBotResponseSeconds <= 45
          ? "warn"
          : "bad";

  return (
    <Card className={`${v.cardClass} lg:col-span-5 xl:col-span-4`}>
      {panelTitle(
        "Sức khỏe chatbot",
        "Ưu tiên tỷ lệ gửi, độ trễ và lỗi thật sự cần xử lý.",
        <Bot className="size-4" />,
        v,
      )}
      <CardContent className={`${v.contentClass} space-y-5`}>
        <DonutMetric
          value={botSuccessRate}
          label="Tỷ lệ gửi thành công"
          caption={`${botSentCount}/${botRunCount} phản hồi đã gửi. Đây là KPI chính thay vì nhìn từng chỉ số rời rạc.`}
          tone={successTone}
        />
        <div className="grid grid-cols-2 gap-3">
          <CompactMetric
            label="Lượt bot"
            value={botRunCount}
            icon={<Activity className="size-3.5" />}
          />
          <CompactMetric
            label="TB phản hồi"
            value={formatSeconds(avgBotResponseSeconds)}
            icon={<Clock3 className="size-3.5" />}
            tone={latencyTone}
          />
          <CompactMetric
            label="Lỗi bot"
            value={botErrors}
            icon={<AlertTriangle className="size-3.5" />}
            tone={botErrors > 0 ? "bad" : "ok"}
          />
          <CompactMetric
            label="Lỗi Zalo"
            value={failedZaloSends}
            icon={<AlertCircle className="size-3.5" />}
            tone={failedZaloSends > 0 ? "bad" : "ok"}
          />
        </div>
      </CardContent>
    </Card>
  );
};

const DeliveryMixCard = ({
  v,
  botRunCount,
  botSentCount,
  botSuppressedCount,
  botSuppressionRate,
  botErrors,
  failedZaloSends,
}: {
  v: VariantConfig;
  botRunCount: number;
  botSentCount: number;
  botSuppressedCount: number;
  botSuppressionRate: number;
  botErrors: number;
  failedZaloSends: number;
}) => {
  const denominator = Math.max(botRunCount, 1);
  const rows = [
    {
      label: "Đã gửi",
      value: botSentCount,
      percent: (botSentCount / denominator) * 100,
      tone: "ok" as Tone,
      detail: "Tin nhắn đã tới kênh chat.",
    },
    {
      label: "Bị chặn",
      value: botSuppressedCount,
      percent: (botSuppressedCount / denominator) * 100,
      tone: botSuppressedCount > 0 ? ("warn" as Tone) : ("neutral" as Tone),
      detail: `${formatRate(botSuppressionRate)} trên tổng bot runs.`,
    },
    {
      label: "Lỗi bot",
      value: botErrors,
      percent: (botErrors / denominator) * 100,
      tone: botErrors > 0 ? ("bad" as Tone) : ("neutral" as Tone),
      detail: "Lỗi xử lý nội bộ trước khi gửi.",
    },
    {
      label: "Lỗi gửi Zalo",
      value: failedZaloSends,
      percent: (failedZaloSends / denominator) * 100,
      tone: failedZaloSends > 0 ? ("bad" as Tone) : ("neutral" as Tone),
      detail: "Có nội dung nhưng kênh gửi thất bại.",
    },
  ];

  return (
    <Card className={`${v.cardClass} lg:col-span-7 xl:col-span-4`}>
      {panelTitle(
        "Kết quả gửi tin",
        "Tách rõ tin đã gửi, tin bị chặn và lỗi cần xử lý.",
        <Send className="size-4" />,
        v,
      )}
      <CardContent className={`${v.contentClass} space-y-4`}>
        {rows.map((row) => (
          <ProgressRow
            key={row.label}
            label={row.label}
            value={row.value}
            percent={row.percent}
            tone={row.tone}
            detail={row.detail}
          />
        ))}
      </CardContent>
    </Card>
  );
};

const KnowledgeStagesCard = ({
  v,
  stageBreakdown,
  publishedCount,
  failedCount,
}: {
  v: VariantConfig;
  stageBreakdown: Array<{ stage: string; count: number }>;
  publishedCount: number;
  failedCount: number;
}) => {
  const total = stageBreakdown.reduce((sum, row) => sum + row.count, 0);
  const maxCount = Math.max(1, ...stageBreakdown.map((row) => row.count));

  return (
    <Card className={`${v.cardClass} lg:col-span-7`}>
      {panelTitle(
        "Dữ liệu huấn luyện",
        "Theo dõi nguồn đã sẵn sàng, nguồn lỗi và tài liệu đang xử lý.",
        <Database className="size-4" />,
        v,
      )}
      <CardContent className={`${v.contentClass} space-y-5`}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <CompactMetric
            label="Tổng nguồn"
            value={total}
            icon={<Database className="size-3.5" />}
          />
          <CompactMetric
            label="Đã xuất bản"
            value={publishedCount}
            icon={<CheckCircle2 className="size-3.5" />}
            tone="ok"
          />
          <CompactMetric
            label="Nguồn lỗi"
            value={failedCount}
            icon={<AlertTriangle className="size-3.5" />}
            tone={failedCount > 0 ? "bad" : "ok"}
          />
        </div>

        <div className="space-y-3">
          {stageBreakdown.length === 0 ? (
            <p className="rounded-lg border border-border/60 bg-muted/20 px-4 py-5 text-sm text-muted-foreground">
              Chưa có nguồn kiến thức.
            </p>
          ) : (
            stageBreakdown.map((row) => (
              <ProgressRow
                key={row.stage}
                label={stageLabel(row.stage)}
                value={row.count}
                percent={(row.count / maxCount) * 100}
                tone={
                  row.stage === "failed"
                    ? "bad"
                    : row.stage === "published"
                      ? "ok"
                      : "busy"
                }
              />
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
};

const KnowledgeOpsCard = ({
  v,
  queueDepth,
  failedJobCount,
  workerCount,
  processingCount,
  stuckCount,
  recentIssues,
}: {
  v: VariantConfig;
  queueDepth: number;
  failedJobCount: number;
  workerCount: number;
  processingCount: number;
  stuckCount: number;
  recentIssues: Array<{
    id: string;
    file_name: string;
    status: string;
    stage: string;
    minutes_since_update: number;
    error?: string | null;
  }>;
}) => {
  const navigate = useNavigate();
  const workerTone: Tone = workerCount === 0 ? "bad" : "neutral";

  return (
    <Card className={`${v.cardClass} lg:col-span-5`}>
      {panelTitle(
        "Cần chú ý",
        "Chỉ giữ những chỉ số cần hành động: worker, queue, stuck jobs và lỗi gần đây.",
        <Server className="size-4" />,
        v,
      )}
      <CardContent className={`${v.contentClass} space-y-5`}>
        <div className="grid grid-cols-2 gap-3">
          <CompactMetric
            label="Đang xử lý"
            value={processingCount}
            icon={<Activity className="size-3.5" />}
            tone={processingCount > 0 ? "busy" : "ok"}
          />
          <CompactMetric
            label="Có thể kẹt"
            value={stuckCount}
            icon={<Clock3 className="size-3.5" />}
            tone={stuckCount > 0 ? "warn" : "ok"}
          />
          <CompactMetric
            label="Hàng đợi xử lý"
            value={queueDepth}
            icon={<Database className="size-3.5" />}
            tone={queueDepth > 0 ? "busy" : "neutral"}
          />
          <CompactMetric
            label="Worker xử lý"
            value={workerCount}
            icon={<Server className="size-3.5" />}
            tone={workerTone}
          />
        </div>

        <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Vấn đề gần đây
            </span>
            <button
              type="button"
              className="text-xs font-bold text-primary hover:text-primary/80"
              onClick={() => navigate("/knowledge_sources")}
            >
              Mở kiến thức
            </button>
          </div>
          {recentIssues.length === 0 ? (
            <p className="rounded-md border border-border/60 bg-background/35 px-3 py-4 text-sm text-muted-foreground">
              Không có nguồn lỗi hoặc đứng quá 10 phút.
            </p>
          ) : (
            <div className="space-y-2">
              {recentIssues.map((issue) => (
                <button
                  key={issue.id}
                  type="button"
                  className="w-full rounded-lg border border-border/60 bg-background/35 px-3 py-3 text-left transition-colors hover:bg-muted/45"
                  onClick={() =>
                    navigate(`/knowledge_sources/${issue.id}/show`)
                  }
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-foreground">
                        {issue.file_name}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {stageLabel(issue.stage)} ·{" "}
                        {v.issueSubtitle(issue.minutes_since_update)}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-md border border-border/70 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                      {issue.status}
                    </span>
                  </div>
                  {issue.error ? (
                    <p className="mt-2 line-clamp-2 text-xs text-destructive">
                      {issue.error}
                    </p>
                  ) : null}
                </button>
              ))}
            </div>
          )}
        </div>

        {failedJobCount > 0 ? (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs font-medium text-amber-700">
            {failedJobCount} RQ job failed. Kiểm tra worker/log trước khi retry
            hàng loạt.
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
};

export const KnowledgeIngestPanel = ({ variant }: { variant: Variant }) => {
  const { permissions } = usePermissions();
  const {
    activeTurns,
    avgBotResponseSeconds,
    botErrors,
    botRunCount,
    botSentCount,
    botSuccessRate,
    botSuppressedCount,
    botSuppressionRate,
    failedZaloSends,
    isPending,
    knowledgeIngest,
    hotLeads,
    openConversations,
    pendingFollowups,
    p95BotResponseSeconds,
    totalLeads,
    turnsLast5min,
    unreadConversationCount,
    webhookQueueDepth,
  } = useDashboardStats();
  const v = V[variant];

  if (permissions === "recruiter") {
    return <Navigate to="/leads" replace />;
  }

  if (isPending) {
    return (
      <div className={v.rootClass}>
        <div
          className={`flex w-full items-center justify-center text-muted-foreground ${v.spinnerClass}`}
        >
          <Activity className="size-8 animate-spin" />
        </div>
      </div>
    );
  }

  return (
    <div className={v.rootClass}>
      <DashboardCommandHeader
        openConversations={openConversations}
        hotLeads={hotLeads}
        pendingFollowups={pendingFollowups}
        activeTurns={activeTurns}
      />
      <DashboardStatusStrip
        totalLeads={totalLeads}
        unreadConversationCount={unreadConversationCount}
        pendingFollowups={pendingFollowups}
        turnsLast5min={turnsLast5min}
        p95BotResponseSeconds={p95BotResponseSeconds}
        webhookQueueDepth={webhookQueueDepth}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
        <ChatbotHealthCard
          v={v}
          botRunCount={botRunCount}
          botSentCount={botSentCount}
          botSuccessRate={botSuccessRate}
          avgBotResponseSeconds={avgBotResponseSeconds}
          botErrors={botErrors}
          failedZaloSends={failedZaloSends}
        />
        <DeliveryMixCard
          v={v}
          botRunCount={botRunCount}
          botSentCount={botSentCount}
          botSuppressedCount={botSuppressedCount}
          botSuppressionRate={botSuppressionRate}
          botErrors={botErrors}
          failedZaloSends={failedZaloSends}
        />
      </div>

      {knowledgeIngest ? (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
          <KnowledgeStagesCard
            v={v}
            stageBreakdown={knowledgeIngest.stage_breakdown}
            publishedCount={knowledgeIngest.published_document_count}
            failedCount={knowledgeIngest.failed_document_count}
          />
          <KnowledgeOpsCard
            v={v}
            queueDepth={knowledgeIngest.queue_depth}
            failedJobCount={knowledgeIngest.failed_job_count}
            workerCount={knowledgeIngest.worker_count}
            processingCount={knowledgeIngest.processing_count}
            stuckCount={knowledgeIngest.stuck_count}
            recentIssues={knowledgeIngest.recent_issues}
          />
        </div>
      ) : null}
    </div>
  );
};
