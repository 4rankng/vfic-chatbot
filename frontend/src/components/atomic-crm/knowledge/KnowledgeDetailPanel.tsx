import { useState } from "react";
import { useNotify, useRedirect, useRefresh } from "ra-core";
import {
  Archive,
  Download,
  MoreHorizontal,
  Pencil,
  RefreshCw,
} from "lucide-react";
import { DeleteButton } from "@/components/admin";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  archiveKnowledge,
  downloadKnowledgeRawFile,
  reindexKnowledge,
} from "@/lib/vfic/knowledgeService";
import { getRelativeTimeString } from "@/lib/utils";
import type { KnowledgeSource, Project } from "../types";
import { stageLabel } from "./stageTone";
import {
  flaggedCount,
  isCanonicalSource,
  isFailed,
  isProcessing,
  isPublished,
  isRunning,
  pipelinePercent,
  pipelineStateCopy,
  sourceStage,
} from "./knowledgePipelineUtils";
import { PipelineMiniProgress, SourceStamp } from "./KnowledgeSourceRow";
import {
  localizeKnowledgeText,
  StoredKnowledgePanel,
} from "./StoredKnowledgePanel";
import { PipelineTimeline } from "./PipelineTimeline";
export const KnowledgeDetailPanel = ({
  source,
  project,
  onBack,
}: {
  source: KnowledgeSource;
  project?: Project;
  onBack?: () => void;
}) => {
  const redirect = useRedirect();
  const notify = useNotify();
  const refresh = useRefresh();
  const flags = flaggedCount(source);
  const [showPipeline, setShowPipeline] = useState(false);
  const processing = isProcessing(source);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      notify(ok, { type: "success" });
      refresh();
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };
  const downloadRawFile = async () => {
    try {
      await downloadKnowledgeRawFile(
        String(source.id),
        source.file_name || "knowledge-source.md",
      );
      notify("Đã tải tệp gốc.", { type: "success" });
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    }
  };

  return (
    <section className="knowledge-detail-panel flex min-h-[620px] flex-col gap-4 bg-transparent text-foreground sm:rounded-[14px] sm:border sm:border-border sm:bg-card sm:p-5 lg:p-6">
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="kb-mono self-start rounded-[9px] px-2 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground lg:hidden"
        >
          ← Quay lại danh sách
        </button>
      )}

      {/* Compact identity — one block, no duplicated stats */}
      <div className="flex items-start justify-between gap-3 px-1 sm:px-0">
        <div className="min-w-0">
          <h3 className="kb-display break-words text-lg text-foreground sm:text-xl">
            {source.file_name}
          </h3>
          <p className="kb-mono mt-1 break-words text-[12.5px] text-muted-foreground">
            {project?.name ?? source.project_name ?? "Chưa gắn dự án"} ·{" "}
            {source.mime_type || "Tài liệu"} · Cập nhật{" "}
            {getRelativeTimeString(source.updated_at ?? source.created_at)}
          </p>
        </div>
        <div className="shrink-0 pt-0.5">
          <SourceStamp source={source} />
        </div>
      </div>

      {/* Single, context-dependent action row */}
      <div className="flex flex-wrap gap-2 border-b border-border px-1 pb-4 sm:px-0">
        <Button
          size="sm"
          onClick={() => redirect("edit", "knowledge_sources", source.id)}
          className="rounded-[9px]"
        >
          <Pencil className="size-4" />
          Sửa
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            run(
              () => reindexKnowledge(String(source.id)),
              "Đã đưa vào hàng huấn luyện lại.",
            )
          }
          className="rounded-[9px]"
        >
          <RefreshCw className="size-4" />
          Huấn luyện lại
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={downloadRawFile}
          className="rounded-[9px]"
        >
          <Download className="size-4" />
          Tải tệp gốc
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              className="rounded-[9px]"
              aria-label={`Mở thao tác cho ${source.file_name}`}
            >
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem
              onSelect={() =>
                run(
                  () => archiveKnowledge(String(source.id)),
                  "Đã lưu trữ. Agent sẽ không dùng nguồn này nữa.",
                )
              }
            >
              <Archive className="size-4" />
              Lưu trữ
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DeleteButton
              record={source}
              resource="knowledge_sources"
              label="Xóa"
              size="sm"
              variant="ghost"
              redirect={false}
              successMessage="Đã xóa tài liệu."
              mutationOptions={{ onSuccess: () => refresh() }}
              className="h-8 w-full justify-start px-2 text-sm text-destructive hover:bg-destructive/10"
            />
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {processing && <PipelineMiniProgress source={source} />}

      {source.error && (
        <div className="rounded-[10px] border border-[var(--kb-rust-soft)] bg-[var(--kb-rust-soft)] p-3 text-sm text-[var(--kb-rust)]">
          {source.error}
        </div>
      )}

      {/* Compact stat trio (units / flagged / updated) — hairline grid */}
      <div className="grid grid-cols-3 gap-px overflow-hidden border-y border-border bg-border sm:rounded-[10px] sm:border-y-0">
        <InfoBlock
          label="Đơn vị"
          value={String(source.digest_meta?.unit_count ?? 0)}
        />
        <InfoBlock label="Cần xem lại" value={String(flags)} />
        <InfoBlock
          label="Cập nhật"
          value={getRelativeTimeString(source.updated_at ?? source.created_at)}
        />
      </div>

      {/* Digest ticket */}
      <div className="px-1 sm:px-0">
        <h4 className="kb-display text-sm text-foreground">
          {isCanonicalSource(source) ? "Tóm tắt nguồn" : "Tóm tắt digest"}
        </h4>
        {source.digest_summary ? (
          <div className="mt-2 border-l-2 border-[var(--kb-line-strong)] py-1 pl-3">
            <p
              className="text-sm italic leading-6 text-[var(--kb-ink-700)]"
              style={{ fontFamily: "var(--kb-font-display)" }}
            >
              {localizeKnowledgeText(source.digest_summary)}
            </p>
          </div>
        ) : (
          <PipelineDigestHint source={source} />
        )}
      </div>

      {/* Extracted knowledge units — the star */}
      <StoredKnowledgePanel source={source} />

      {/* Pipeline detail — collapsed, demoted */}
      <div className="px-1 sm:px-0">
        <button
          type="button"
          onClick={() => setShowPipeline((value) => !value)}
          className="flex w-full items-center justify-between gap-2 border-y border-border py-3 text-left text-sm font-semibold text-foreground transition-colors hover:text-[var(--kb-teal)] sm:rounded-[10px] sm:border sm:bg-background sm:px-4 sm:hover:bg-secondary"
        >
          <span>Chi tiết pipeline (6 bước)</span>
          <span className="kb-mono text-xs text-muted-foreground">
            {pipelinePercent(source)}% ·{" "}
            {isFailed(source)
              ? "Lỗi"
              : isPublished(source)
                ? "Sẵn sàng"
                : stageLabel(sourceStage(source), {
                    isCanonical: isCanonicalSource(source),
                  })}
          </span>
        </button>
        {showPipeline && (
          <div className="mt-2 border-b border-border pb-4 sm:rounded-[10px] sm:border sm:bg-background sm:p-4">
            <p className="mb-3 text-xs leading-5 text-muted-foreground">
              {pipelineStateCopy(source)}
            </p>
            <PipelineTimeline source={source} />
          </div>
        )}
      </div>
    </section>
  );
};

const InfoBlock = ({ label, value }: { label: string; value: string }) => (
  <div className="min-w-0 bg-background px-3 py-3 sm:bg-card sm:px-4">
    <div className="kb-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
      {label}
    </div>
    <div className="kb-mono mt-1.5 break-words text-lg font-semibold text-foreground">
      {value}
    </div>
  </div>
);

const PipelineDigestHint = ({ source }: { source: KnowledgeSource }) => {
  if (isRunning(source)) {
    return (
      <div className="mt-2 flex items-center gap-2 rounded-[10px] bg-[var(--kb-teal-soft)] p-3 text-sm text-[var(--kb-teal)]">
        <RefreshCw className="size-4 animate-spin" />
        {isCanonicalSource(source)
          ? "Đang chuẩn hóa Markdown và tạo đơn vị truy xuất."
          : "Đang xử lý trong pipeline. Tóm tắt sẽ xuất hiện sau khi digest hoàn tất."}
      </div>
    );
  }

  if (isFailed(source)) {
    return (
      <div className="mt-2 rounded-[10px] bg-[var(--kb-rust-soft)] p-3 text-sm text-[var(--kb-rust)]">
        Pipeline đã lỗi trước khi tạo tóm tắt. Huấn luyện lại hoặc kiểm tra định
        dạng nguồn nếu lỗi lặp lại.
      </div>
    );
  }

  return (
    <div className="mt-2 border-l-2 border-[var(--kb-line-strong)] py-1 pl-3">
      <p
        className="text-sm italic leading-6 text-[var(--kb-ink-300)]"
        style={{ fontFamily: "var(--kb-font-display)" }}
      >
        Pipeline chưa trả về tóm tắt cho nguồn này. Tóm tắt sẽ hiện ra ở đây sau
        khi xử lý xong.
      </p>
    </div>
  );
};
