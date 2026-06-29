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

export const MobileDashboard = () => {
  const navigate = useNavigate();
  const { permissions } = usePermissions();
  const { knowledgeIngest, isPending } = useDashboardStats();

  if (permissions === "recruiter") {
    return <Navigate to="/leads" replace />;
  }

  return (
    <main className="mx-auto flex w-full max-w-screen-xl flex-col gap-5 px-4 py-5">
      {isPending ? (
        <div className="w-full h-[200px] flex items-center justify-center text-muted-foreground">
          <Activity className="size-6 animate-spin" />
        </div>
      ) : knowledgeIngest ? (
        <Card className="border border-border bg-card shadow-xs">
          <CardHeader className="pb-3 pt-4 px-4">
            <CardTitle className="flex items-center gap-2">
              <span className="w-1.5 h-4.5 bg-primary rounded-full" />
              <span className="font-display text-base font-bold tracking-wider uppercase text-foreground">
                Knowledge ingest
              </span>
            </CardTitle>
            <CardDescription className="text-[11px] text-muted-foreground">
              Tín hiệu vận hành để quyết định retry, restart worker hoặc kiểm tra
              LLM
            </CardDescription>
          </CardHeader>
          <CardContent className="px-4 pb-4 flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3">
              <MobileIngestMetric
                label="Đang xử lý"
                value={knowledgeIngest.processing_count}
                icon={<Activity className="size-3.5" />}
                tone={knowledgeIngest.processing_count > 0 ? "busy" : "ok"}
              />
              <MobileIngestMetric
                label="Có thể kẹt"
                value={knowledgeIngest.stuck_count}
                icon={<Clock3 className="size-3.5" />}
                tone={knowledgeIngest.stuck_count > 0 ? "warn" : "ok"}
              />
              <MobileIngestMetric
                label="Nguồn lỗi"
                value={knowledgeIngest.failed_document_count}
                icon={<AlertTriangle className="size-3.5" />}
                tone={
                  knowledgeIngest.failed_document_count > 0 ? "bad" : "ok"
                }
              />
              <MobileIngestMetric
                label="Đã xuất bản"
                value={knowledgeIngest.published_document_count}
                icon={<CheckCircle2 className="size-3.5" />}
                tone="ok"
              />
            </div>

            <div className="grid grid-cols-3 gap-2">
              <MobileIngestMetric
                label="Queue"
                value={knowledgeIngest.queue_depth}
                icon={<Database className="size-3" />}
                tone={knowledgeIngest.queue_depth > 0 ? "busy" : "neutral"}
              />
              <MobileIngestMetric
                label="RQ failed"
                value={knowledgeIngest.failed_job_count}
                icon={<AlertCircle className="size-3" />}
                tone={
                  knowledgeIngest.failed_job_count > 0 ? "warn" : "neutral"
                }
              />
              <MobileIngestMetric
                label="Worker"
                value={knowledgeIngest.worker_count}
                icon={<Server className="size-3" />}
                tone={knowledgeIngest.worker_count === 0 ? "bad" : "neutral"}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                <span>Các bước xử lý</span>
                <span>{knowledgeIngest.stage_breakdown.length} trạng thái</span>
              </div>
              {knowledgeIngest.stage_breakdown.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Chưa có nguồn kiến thức.
                </p>
              ) : (
                knowledgeIngest.stage_breakdown.map((row) => (
                  <div
                    key={row.stage}
                    className="flex items-center gap-2 rounded-lg bg-muted/20 px-2.5 py-1.5"
                  >
                    <div className="w-28 text-[10px] font-semibold text-muted-foreground truncate">
                      {stageLabel(row.stage)}
                    </div>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted/60">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{
                          width: `${Math.min(100, Math.max(8, row.count * 12))}%`,
                        }}
                      />
                    </div>
                    <div className="w-8 text-right text-xs font-semibold font-mono">
                      {row.count}
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
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
                <div className="rounded-lg border border-border/60 bg-muted/25 px-3 py-4 text-xs text-muted-foreground">
                  Không có nguồn lỗi hoặc đứng quá 10 phút.
                </div>
              ) : (
                <div className="space-y-2">
                  {knowledgeIngest.recent_issues.map((issue) => (
                    <button
                      key={issue.id}
                      type="button"
                      className="w-full rounded-lg border border-border/60 bg-muted/20 px-2.5 py-2 text-left transition-colors hover:bg-muted/45"
                      onClick={() =>
                        navigate(`/knowledge_sources/${issue.id}/show`)
                      }
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-xs font-semibold text-foreground">
                            {issue.file_name}
                          </p>
                          <p className="mt-0.5 text-[10px] text-muted-foreground">
                            {stageLabel(issue.stage)} ·{" "}
                            {issue.minutes_since_update} phút
                          </p>
                        </div>
                        <span className="shrink-0 rounded-md border border-border/70 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-muted-foreground">
                          {issue.status}
                        </span>
                      </div>
                      {issue.error && (
                        <p className="mt-1 line-clamp-2 text-[10px] text-destructive">
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
    </main>
  );
};

const MobileIngestMetric = ({
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
    <div className="rounded-lg border border-border/60 bg-muted/20 px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[9px] font-bold uppercase tracking-wider text-muted-foreground truncate">
          {label}
        </span>
        <span className={`rounded-md border p-1 ${toneClass}`}>{icon}</span>
      </div>
      <div className="mt-2 text-lg font-semibold font-mono tracking-tight text-foreground">
        {value}
      </div>
    </div>
  );
};
