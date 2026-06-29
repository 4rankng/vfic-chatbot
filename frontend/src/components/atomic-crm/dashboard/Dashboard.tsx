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
  CheckCircle2,
  Clock3,
  Database,
  Server,
} from "lucide-react";
import { useNavigate, Navigate } from "react-router";
import { usePermissions } from "ra-core";
import { useDashboardStats } from "./useDashboardStats";
import { stageLabel } from "../knowledge/stageTone";

export const Dashboard = () => {
  const navigate = useNavigate();
  const { permissions } = usePermissions();
  const { knowledgeIngest, isPending } = useDashboardStats();

  if (permissions === "recruiter") {
    return <Navigate to="/leads" replace />;
  }

  return (
    <div className="flex flex-col gap-6 mx-auto w-full pb-8">
      {isPending ? (
        <div className="w-full h-[300px] flex items-center justify-center text-muted-foreground">
          <Activity className="w-8 h-8 animate-spin" />
        </div>
      ) : knowledgeIngest ? (
        <Card className="bg-card">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <span className="w-1.5 h-4.5 bg-primary rounded-full" />
              <span className="font-display text-xl font-bold tracking-wider uppercase text-foreground">
                Knowledge ingest
              </span>
            </CardTitle>
            <CardDescription className="text-xs text-muted-foreground">
              Tín hiệu vận hành để quyết định retry, restart worker hoặc kiểm tra
              LLM
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
                  tone={
                    knowledgeIngest.failed_document_count > 0 ? "bad" : "ok"
                  }
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
                  tone={
                    knowledgeIngest.failed_job_count > 0 ? "warn" : "neutral"
                  }
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
                  <span>Các bước xử lý</span>
                  <span>
                    {knowledgeIngest.stage_breakdown.length} trạng thái
                  </span>
                </div>
                <div className="space-y-2">
                  {knowledgeIngest.stage_breakdown.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      Chưa có nguồn kiến thức.
                    </p>
                  ) : (
                    knowledgeIngest.stage_breakdown.map((row) => (
                      <StageRow
                        key={row.stage}
                        stage={row.stage}
                        count={row.count}
                      />
                    ))
                  )}
                </div>
              </div>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider text-muted-foreground">
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
                      onClick={() =>
                        navigate(`/knowledge_sources/${issue.id}/show`)
                      }
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-foreground">
                            {issue.file_name}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {stageLabel(issue.stage)} ·{" "}
                            {issue.minutes_since_update} phút chưa cập nhật
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
      ) : null}
    </div>
  );
};

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

const StageRow = ({
  stage,
  count,
}: {
  stage: string;
  count: number;
}) => (
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
    <div className="w-10 text-right text-sm font-semibold font-mono">
      {count}
    </div>
  </div>
);
