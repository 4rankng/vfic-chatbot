import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { TopToolbar } from "../layout/TopToolbar";
import {
  Users,
  UserCheck,
  TrendingUp,
  Activity,
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Database,
  Server,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useDashboardStats } from "./useDashboardStats";
import { stageLabel } from "../knowledge/stageTone";

export const Dashboard = () => {
  const navigate = useNavigate();

  const {
    totalLeads: totalLeadsCount,
    qualifiedCount: qualifiedLeads,
    unreadConversationCount: unreadConvs,
    hiredRate,
    stageBreakdown,
    knowledgeIngest,
    isPending: isLoading,
  } = useDashboardStats();

  return (
    <div className="flex flex-col gap-6 mx-auto w-full pb-8">
      <TopToolbar className="flex-col items-start md:flex-row md:items-end gap-4 pb-5 mb-2">
        <div className="mr-auto">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Tổng quan phân tích
          </h2>
          <p className="text-muted-foreground text-sm font-medium mt-1">
            Hiệu suất tuyển dụng trên mọi quy trình đang hoạt động
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <span>Tất cả quy trình</span>
          <span>•</span>
          <span>30 ngày qua</span>
          <span>•</span>
          <span>Cập nhật 5 phút trước</span>
        </div>
      </TopToolbar>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <KpiCard
          title="Tổng khách hàng"
          value={
            isLoading ? "..." : totalLeadsCount.toString().padStart(2, "0")
          }
          description="Trên tất cả quy trình"
          icon={<Users className="w-4 h-4" />}
          trend="+12%"
          trendUp={true}
        />
        <KpiCard
          title="Cần phản hồi"
          value={isLoading ? "..." : unreadConvs.toString().padStart(2, "0")}
          description="Đợi nhân viên phản hồi"
          icon={<AlertCircle className="w-4 h-4" />}
          trend={unreadConvs > 0 ? `${unreadConvs} đang xử lý` : undefined}
          trendUp={false}
          neutral={unreadConvs === 0}
        />
        <KpiCard
          title="Ứng viên đạt chuẩn"
          value={isLoading ? "..." : qualifiedLeads.toString().padStart(2, "0")}
          description="Sẵn sàng tuyển dụng"
          icon={<UserCheck className="w-4 h-4" />}
          trend="+5%"
          trendUp={true}
        />
        <KpiCard
          title="Tỷ lệ chuyển đổi"
          value={isLoading ? "..." : `${hiredRate}%`}
          description="Tỷ lệ khách hàng thành tuyển dụng"
          icon={<TrendingUp className="w-4 h-4" />}
          trend={hiredRate === 0 ? "Giai đoạn đầu" : "Đang hoạt động"}
          trendUp={hiredRate > 0}
          neutral={hiredRate === 0}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Main Chart */}
        <Card className="md:col-span-2 bg-card">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <span className="w-1.5 h-4.5 bg-primary rounded-full" />
              <span className="font-display text-xl font-bold tracking-wider uppercase text-foreground">
                Phân bổ quy trình
              </span>
            </CardTitle>
            <CardDescription className="text-xs text-muted-foreground">
              Tổng quan khách hàng trên các giai đoạn
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-3">
              {isLoading ? (
                <div className="w-full h-[200px] flex items-center justify-center text-muted-foreground">
                  <Activity className="w-8 h-8 animate-spin" />
                </div>
              ) : (
                stageBreakdown.map((stage) => {
                  const count = stage.count;
                  const percentage = stage.percentage;
                  // extract color for bg
                  const bgClass = stage.color;
                  return (
                    <div
                      key={stage.value}
                      className="flex items-center gap-4 cursor-pointer hover:bg-muted/40 p-2.5 rounded-xl transition-all"
                      onClick={() =>
                        navigate(
                          `/leads?filter=%7B"lead_stage"%3A"${stage.value}"%7D`,
                        )
                      }
                    >
                      <div className="w-24 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        {stage.label}
                      </div>
                      <div className="w-8 text-sm font-semibold font-mono text-right">
                        {count}
                      </div>
                      <div className="flex-1 h-2 bg-muted/60 rounded-full overflow-hidden flex">
                        <div
                          className={`h-full ${bgClass} rounded-full`}
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                      <div className="w-12 text-xs font-semibold font-mono text-muted-foreground text-right">
                        {percentage}%
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </CardContent>
        </Card>

        {/* Side Panel */}
        <Card className="bg-card flex flex-col">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <span className="w-1.5 h-4.5 bg-primary rounded-full" />
              <span className="font-display text-xl font-bold tracking-wider uppercase text-foreground">
                Hoạt động hệ thống
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 flex flex-col gap-6">
            <div
              className="space-y-2 cursor-pointer hover:bg-muted/50 p-2 rounded-md transition-colors -mx-2"
              onClick={() => navigate("/conversations")}
            >
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-amber-500" />
                Cần chú ý
              </h4>
              <p className="text-xs text-muted-foreground ml-6">
                {unreadConvs} cuộc trò chuyện cần phản hồi
              </p>
            </div>

            <div
              className="space-y-2 cursor-pointer hover:bg-muted/50 p-2 rounded-md transition-colors -mx-2"
              onClick={() =>
                navigate(`/leads?filter=%7B"lead_stage"%3A"QUALIFIED"%7D`)
              }
            >
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <UserCheck className="w-4 h-4 text-cyan-500" />
                Ứng viên đạt chuẩn
              </h4>
              <p className="text-xs text-muted-foreground ml-6">
                {qualifiedLeads} ứng viên cần xem xét
              </p>
            </div>

            <div className="space-y-2 cursor-pointer hover:bg-muted/50 p-2 rounded-md transition-colors -mx-2">
              <h4 className="text-sm font-semibold flex items-center gap-2">
                <Activity className="w-4 h-4 text-emerald-500" />
                Hoạt động gần đây
              </h4>
              <p className="text-xs text-muted-foreground ml-6">
                Quy trình cập nhật · 12 phút trước
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {knowledgeIngest && (
        <Card className="bg-card">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <span className="w-1.5 h-4.5 bg-primary rounded-full" />
              <span className="font-display text-xl font-bold tracking-wider uppercase text-foreground">
                Knowledge ingest
              </span>
            </CardTitle>
            <CardDescription className="text-xs text-muted-foreground">
              Tín hiệu vận hành để quyết định retry, restart worker hoặc kiểm tra LLM
            </CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)] gap-6">
            <div className="space-y-5">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <IngestMetric
                  label="Đang xử lý"
                  value={knowledgeIngest.processing_count}
                  icon={<Activity className="w-4 h-4" />}
                  tone={knowledgeIngest.processing_count > 0 ? "busy" : "ok"}
                />
                <IngestMetric
                  label="Có thể kẹt"
                  value={knowledgeIngest.stuck_count}
                  icon={<Clock3 className="w-4 h-4" />}
                  tone={knowledgeIngest.stuck_count > 0 ? "warn" : "ok"}
                />
                <IngestMetric
                  label="Nguồn lỗi"
                  value={knowledgeIngest.failed_document_count}
                  icon={<AlertTriangle className="w-4 h-4" />}
                  tone={knowledgeIngest.failed_document_count > 0 ? "bad" : "ok"}
                />
                <IngestMetric
                  label="Đã xuất bản"
                  value={knowledgeIngest.published_document_count}
                  icon={<CheckCircle2 className="w-4 h-4" />}
                  tone="ok"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <IngestMetric
                  label="Queue ingest"
                  value={knowledgeIngest.queue_depth}
                  icon={<Database className="w-4 h-4" />}
                  tone={knowledgeIngest.queue_depth > 0 ? "busy" : "neutral"}
                />
                <IngestMetric
                  label="RQ failed"
                  value={knowledgeIngest.failed_job_count}
                  icon={<AlertCircle className="w-4 h-4" />}
                  tone={knowledgeIngest.failed_job_count > 0 ? "warn" : "neutral"}
                />
                <IngestMetric
                  label="Worker"
                  value={knowledgeIngest.worker_count}
                  icon={<Server className="w-4 h-4" />}
                  tone={knowledgeIngest.worker_count === 0 ? "bad" : "neutral"}
                />
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  <span>Pipeline stages</span>
                  <span>{knowledgeIngest.stage_breakdown.length} trạng thái</span>
                </div>
                <div className="space-y-2">
                  {knowledgeIngest.stage_breakdown.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Chưa có nguồn kiến thức.</p>
                  ) : (
                    knowledgeIngest.stage_breakdown.map((row) => (
                      <StageRow key={row.stage} stage={row.stage} count={row.count} />
                    ))
                  )}
                </div>
              </div>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider text-muted-foreground">
                <span>Recent issues</span>
                <button
                  type="button"
                  className="text-primary hover:text-primary/80"
                  onClick={() => navigate("/knowledge_sources")}
                >
                  Mở kiến thức
                </button>
              </div>
              {knowledgeIngest.recent_issues.length === 0 ? (
                <div className="rounded-lg border border-border/60 bg-muted/25 px-4 py-5 text-sm text-muted-foreground">
                  Không có nguồn lỗi hoặc đứng quá 10 phút.
                </div>
              ) : (
                <div className="space-y-2">
                  {knowledgeIngest.recent_issues.map((issue) => (
                    <button
                      key={issue.id}
                      type="button"
                      className="w-full rounded-lg border border-border/60 bg-muted/20 px-3 py-3 text-left transition-colors hover:bg-muted/45"
                      onClick={() => navigate(`/knowledge_sources/${issue.id}/show`)}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-foreground">
                            {issue.file_name}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {stageLabel(issue.stage)} · {issue.minutes_since_update} phút chưa cập nhật
                          </p>
                        </div>
                        <span className="shrink-0 rounded-md border border-border/70 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                          {issue.status}
                        </span>
                      </div>
                      {issue.error && (
                        <p className="mt-2 line-clamp-2 text-xs text-destructive">
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
      )}
    </div>
  );
};

// Reusable KPI Component
const KpiCard = ({
  title,
  value,
  description,
  icon,
  trend,
  trendUp,
  neutral,
}: {
  title: string;
  value: string;
  description: string;
  icon: React.ReactNode;
  trend?: string;
  trendUp?: boolean;
  neutral?: boolean;
}) => (
  <Card className="bg-card transition-colors duration-300 group overflow-hidden relative">
    <CardHeader className="flex flex-row items-center justify-between pb-3">
      <CardTitle className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        {title}
      </CardTitle>
      <div className="p-2 bg-muted/40 text-muted-foreground border border-border/50 rounded-lg group-hover:bg-primary/10 group-hover:text-primary group-hover:border-primary/20 transition-colors">
        {icon}
      </div>
    </CardHeader>
    <CardContent className="pb-4">
      <div className="text-4xl font-semibold font-mono tracking-tight text-foreground">
        {value}
      </div>
      <div className="flex items-center mt-2 space-x-2">
        <p className="text-[11px] font-medium text-muted-foreground/80">
          {description}
        </p>
        {trend && (
          <span
            className={`text-[10px] font-bold font-mono px-2 py-0.5 rounded-full ${
              neutral
                ? "bg-muted-dim/15 text-muted-dim"
                : trendUp
                  ? "bg-green/12 text-green"
                  : "bg-destructive/12 text-destructive"
            }`}
          >
            {trend}
          </span>
        )}
      </div>
    </CardContent>
  </Card>
);

const IngestMetric = ({
  label,
  value,
  icon,
  tone,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  tone: "ok" | "busy" | "warn" | "bad" | "neutral";
}) => {
  const toneClass = {
    ok: "text-emerald-600 bg-emerald-500/10 border-emerald-500/20",
    busy: "text-sky-600 bg-sky-500/10 border-sky-500/20",
    warn: "text-amber-600 bg-amber-500/10 border-amber-500/20",
    bad: "text-destructive bg-destructive/10 border-destructive/20",
    neutral: "text-muted-foreground bg-muted/30 border-border/70",
  }[tone];

  return (
    <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <span className={`rounded-md border p-1.5 ${toneClass}`}>{icon}</span>
      </div>
      <div className="mt-3 text-2xl font-semibold font-mono tracking-tight text-foreground">
        {value}
      </div>
    </div>
  );
};

const StageRow = ({ stage, count }: { stage: string; count: number }) => (
  <div className="flex items-center gap-3 rounded-lg bg-muted/20 px-3 py-2">
    <div className="w-36 text-xs font-semibold text-muted-foreground">
      {stageLabel(stage)}
    </div>
    <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted/60">
      <div
        className="h-full rounded-full bg-primary"
        style={{ width: `${Math.min(100, Math.max(8, count * 12))}%` }}
      />
    </div>
    <div className="w-10 text-right text-sm font-semibold font-mono">{count}</div>
  </div>
);
