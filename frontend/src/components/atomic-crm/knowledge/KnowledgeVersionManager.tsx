import { useCallback, useEffect, useState } from "react";
import { History, RefreshCw, Send } from "lucide-react";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { CloseButton } from "@/components/base/buttons/close-button";
import {
  Dialog,
  DialogTrigger,
  Modal,
  ModalOverlay,
} from "@/components/application/modals/modal";
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
    <DialogTrigger isOpen={open} onOpenChange={setOpen}>
      <Button
        color="secondary"
        size="sm"
        iconLeading={History}
        isDisabled={!projectId}
      >
        Phiên bản KB
      </Button>
      <ModalOverlay className="uu-scope">
        <Modal className="w-full outline-hidden sm:max-w-xl">
          <Dialog
            aria-label="Phiên bản kiến thức"
            className="flex flex-col gap-0 p-0 outline-hidden"
          >
            <header className="sticky top-0 z-10 border-b border-secondary bg-primary px-5 py-4 pr-14 text-left sm:px-6 sm:py-5">
              <h2 className="text-lg font-semibold text-primary">
                Phiên bản kiến thức
              </h2>
              <p className="mt-1 text-sm text-tertiary">
                Chỉ phiên bản READY mới có thể được xuất bản. Việc xuất bản sẽ
                thay thế toàn bộ KB đang hoạt động của dự án.
              </p>
              <CloseButton
                size="sm"
                label="Đóng"
                className="absolute top-3 right-3"
              />
            </header>
            <div className="flex flex-col gap-3 px-5 py-5 sm:px-6">
              {error ? (
                <p className="rounded-lg border border-error_subtle bg-error-primary px-3 py-2 text-sm font-medium text-error-primary">
                  {error}
                </p>
              ) : null}
              <div className="max-h-[55vh] space-y-2 overflow-y-auto">
                {versions.map((version) => (
                  <div
                    key={version.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-secondary p-3"
                  >
                    <div>
                      <p className="text-sm font-medium text-primary">
                        Phiên bản {version.version_no}
                      </p>
                      <p className="text-xs text-tertiary">
                        Phiên bản KB theo dự án
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge
                        type="pill-color"
                        size="sm"
                        color={version.status === "READY" ? "success" : "gray"}
                      >
                        {version.status}
                      </Badge>
                      {version.status === "READY" ? (
                        <Button
                          color="primary"
                          size="sm"
                          isDisabled={busyId === version.id}
                          iconLeading={
                            busyId === version.id ? (
                              <RefreshCw className="size-4 animate-spin" />
                            ) : (
                              Send
                            )
                          }
                          onClick={() => void publish(version)}
                        >
                          Xuất bản
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ))}
                {versions.length === 0 ? (
                  <p className="py-8 text-center text-sm text-tertiary">
                    Chưa có phiên bản KB.
                  </p>
                ) : null}
              </div>
            </div>
          </Dialog>
        </Modal>
      </ModalOverlay>
    </DialogTrigger>
  );
};
