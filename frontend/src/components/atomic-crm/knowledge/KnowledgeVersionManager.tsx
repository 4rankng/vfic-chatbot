import { useEffect, useState } from "react";
import { History, RefreshCw, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  listKnowledgeBaseVersions,
  listKnowledgeBaseVersionRuns,
  publishKnowledgeBaseVersion,
  reviewKnowledgeIngestionRun,
  type KnowledgeIngestionRun,
  type KnowledgeBaseVersion,
} from "@/lib/vfic/knowledgeService";

export const KnowledgeVersionManager = ({ projectId }: { projectId?: string }) => {
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState<KnowledgeBaseVersion[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runsByVersion, setRunsByVersion] = useState<Record<string, KnowledgeIngestionRun[]>>({});

  const load = async () => {
    if (!projectId) return;
    setError(null);
    try {
      const result = await listKnowledgeBaseVersions(projectId);
      setVersions(result.data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không tải được phiên bản KB.");
    }
  };

  useEffect(() => {
    if (open) void load();
  }, [open, projectId]);

  const publish = async (version: KnowledgeBaseVersion) => {
    if (!projectId) return;
    setBusyId(version.id);
    setError(null);
    try {
      await publishKnowledgeBaseVersion(projectId, version.id);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không thể xuất bản phiên bản KB.");
    } finally {
      setBusyId(null);
    }
  };

  const loadRuns = async (version: KnowledgeBaseVersion) => {
    if (!projectId) return;
    try {
      const runs = await listKnowledgeBaseVersionRuns(projectId, version.id);
      setRunsByVersion((current) => ({ ...current, [version.id]: runs }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không tải được kết quả ingest.");
    }
  };

  const review = async (run: KnowledgeIngestionRun, decision: "approve" | "reject") => {
    const comment = window.prompt(
      decision === "approve" ? "Ghi chú phê duyệt" : "Lý do từ chối",
    );
    if (!comment?.trim()) return;
    setBusyId(run.id);
    try {
      await reviewKnowledgeIngestionRun(run.id, decision, comment.trim());
      const version = versions.find((item) => item.id === run.kb_version_id);
      if (version) await loadRuns(version);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không thể ghi nhận quyết định xem lại.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" className="h-10 rounded-[9px]" disabled={!projectId}>
          <History className="size-4" /> Phiên bản KB
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Phiên bản kiến thức</DialogTitle>
          <DialogDescription>Chỉ phiên bản READY mới có thể được xuất bản. Việc xuất bản sẽ thay thế toàn bộ KB đang hoạt động của dự án.</DialogDescription>
        </DialogHeader>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <div className="max-h-[55vh] space-y-2 overflow-y-auto">
          {versions.map((version) => (
            <div key={version.id} className="space-y-2">
              <div className="flex items-center justify-between gap-3 rounded-md border p-3">
                <div>
                  <p className="text-sm font-medium">Phiên bản {version.version_no}</p>
                  <p className="text-xs text-muted-foreground">Mẫu: {version.template_version_id ?? "Tuyển dụng tích hợp"}</p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{version.status}</Badge>
                  {version.status === "READY" && <Button size="sm" disabled={busyId === version.id} onClick={() => void publish(version)}>{busyId === version.id ? <RefreshCw className="size-4 animate-spin" /> : <Send className="size-4" />} Xuất bản</Button>}
                  {version.status === "REVIEW_REQUIRED" && <Button size="sm" variant="outline" onClick={() => void loadRuns(version)}>Xem lại</Button>}
                </div>
              </div>
              {runsByVersion[version.id]?.map((run) => (
                <div key={run.id} className="ml-3 rounded-md bg-muted/50 p-3 text-xs">
                  <p className="font-medium">Lần ingest {run.attempt_no}: {run.status}</p>
                  {run.issues.length > 0 && <ul className="mt-1 list-disc pl-4 text-muted-foreground">{run.issues.map((issue) => <li key={`${issue.code}-${issue.message}`}>{issue.message}</li>)}</ul>}
                  {run.status === "REVIEW_REQUIRED" && <div className="mt-2 flex gap-2"><Button size="sm" onClick={() => void review(run, "approve")} disabled={busyId === run.id}>Phê duyệt</Button><Button size="sm" variant="outline" onClick={() => void review(run, "reject")} disabled={busyId === run.id}>Từ chối</Button></div>}
                </div>
              ))}
            </div>
          ))}
          {versions.length === 0 && <p className="py-8 text-center text-sm text-muted-foreground">Chưa có phiên bản KB.</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
};
