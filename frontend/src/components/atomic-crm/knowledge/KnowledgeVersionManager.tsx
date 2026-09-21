import { useCallback, useEffect, useState } from "react";
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
  publishKnowledgeBaseVersion,
  type KnowledgeBaseVersion,
} from "./knowledge-service";

export const KnowledgeVersionManager = ({
  projectId,
}: {
  projectId?: string;
}) => {
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState<KnowledgeBaseVersion[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    setError(null);
    try {
      const result = await listKnowledgeBaseVersions(projectId);
      setVersions(result.data);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Không tải được phiên bản KB.",
      );
    }
  }, [projectId]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const publish = async (version: KnowledgeBaseVersion) => {
    if (!projectId) return;
    setBusyId(version.id);
    setError(null);
    try {
      await publishKnowledgeBaseVersion(projectId, version.id);
      await load();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Không thể xuất bản phiên bản KB.",
      );
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="tt-btn-touch h-11 rounded-[9px]"
          disabled={!projectId}
        >
          <History className="size-4" /> Phiên bản KB
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Phiên bản kiến thức</DialogTitle>
          <DialogDescription>
            Chỉ phiên bản READY mới có thể được xuất bản. Việc xuất bản sẽ thay
            thế toàn bộ KB đang hoạt động của dự án.
          </DialogDescription>
        </DialogHeader>
        {error && <p className="text-body text-destructive">{error}</p>}
        <div className="max-h-[55vh] space-y-2 overflow-y-auto">
          {versions.map((version) => (
            <div key={version.id} className="space-y-2">
              <div className="flex items-center justify-between gap-3 rounded-md border p-3">
                <div>
                  <p className="text-row-title font-medium">
                    Phiên bản {version.version_no}
                  </p>
                  <p className="text-helper text-muted-foreground">
                    Phiên bản KB theo dự án
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{version.status}</Badge>
                  {version.status === "READY" && (
                    <Button
                      size="sm"
                      disabled={busyId === version.id}
                      onClick={() => void publish(version)}
                    >
                      {busyId === version.id ? (
                        <RefreshCw className="size-4 animate-spin" />
                      ) : (
                        <Send className="size-4" />
                      )}{" "}
                      Xuất bản
                    </Button>
                  )}
                </div>
              </div>
            </div>
          ))}
          {versions.length === 0 && (
            <p className="py-8 text-center text-body text-muted-foreground">
              Chưa có phiên bản KB.
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};
