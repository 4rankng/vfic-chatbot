import { useState } from "react";
import type { Key } from "react-aria-components";
import {
  useDeleteWithUndoController,
  useNotify,
  useRedirect,
  useRefresh,
} from "ra-core";
import {
  Archive,
  ArrowLeft,
  Download,
  LoaderCircle,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/base/buttons/button";
import { Dropdown } from "@/components/base/dropdown/dropdown";
import {
  archiveKnowledge,
  downloadKnowledgeRawFile,
  reindexKnowledge,
} from "./knowledge-service";
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
import { StoredKnowledgePanel } from "./StoredKnowledgePanel";
import { localizeKnowledgeText } from "./domain/knowledge-text";
import { PipelineTimeline } from "./PipelineTimeline";
export const KnowledgeDetailPanel = ({
  source,
  project,
  onBack,
  headingId,
  headingAs: Heading = "h3",
}: {
  source: KnowledgeSource;
  project?: Project;
  onBack?: () => void;
  headingId?: string;
  headingAs?: "h1" | "h2" | "h3";
}) => {
  const redirect = useRedirect();
  const notify = useNotify();
  const refresh = useRefresh();
  const flags = flaggedCount(source);
  const [showPipeline, setShowPipeline] = useState(false);
  const [pendingAction, setPendingAction] = useState<
    "reindex" | "download" | "archive" | null
  >(null);
  const processing = isProcessing(source);
  const { isPending: deletePending, handleDelete } =
    useDeleteWithUndoController({
      record: source,
      resource: "knowledge_sources",
      redirect: false,
      successMessage: "Đã xóa tài liệu.",
      mutationOptions: { onSuccess: () => refresh() },
    });

  const handleDetailAction = (key: Key) => {
    if (key === "archive") {
      void run(
        "archive",
        () => archiveKnowledge(String(source.id)),
        "Đã lưu trữ. Agent sẽ không dùng nguồn này nữa.",
      );
    }
    if (key === "delete") handleDelete(undefined as never);
  };

  const run = async (
    action: Exclude<typeof pendingAction, null>,
    fn: () => Promise<unknown>,
    ok: string,
    refreshAfter = true,
  ) => {
    if (pendingAction) return;
    setPendingAction(action);
    try {
      await fn();
      notify(ok, { type: "success" });
      if (refreshAfter) refresh();
    } catch (err) {
      notify(`Thất bại: ${(err as Error).message}`, { type: "error" });
    } finally {
      setPendingAction(null);
    }
  };

  return (
    <section className="knowledge-detail-panel flex flex-col bg-transparent text-foreground">
      {onBack && (
        <Button
          type="button"
          color="tertiary"
          size="sm"
          data-slot="button"
          onClick={onBack}
          iconLeading={ArrowLeft}
          className="kb-mono min-h-11 self-start rounded-[9px] px-3 lg:hidden"
        >
          Quay lại danh sách
        </Button>
      )}

      {/* Compact identity — one block, no duplicated stats */}
      <div className="knowledge-detail-identity flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Heading
            id={headingId}
            className="kb-display break-words text-subsection text-foreground sm:text-content-title"
          >
            {source.file_name}
          </Heading>
          <p className="kb-mono mt-1 break-words text-meta text-muted-foreground">
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
      <div className="knowledge-detail-actions flex flex-wrap gap-2">
        <Button
          type="button"
          data-slot="button"
          isDisabled={pendingAction !== null}
          onClick={() => redirect("edit", "knowledge_sources", source.id)}
          iconLeading={Pencil}
          className="tt-btn-touch uu-scope rounded-[9px]"
        >
          Sửa
        </Button>
        <Button
          type="button"
          color="secondary"
          data-slot="button"
          isDisabled={pendingAction !== null}
          onClick={() =>
            run(
              "reindex",
              () => reindexKnowledge(String(source.id)),
              "Đã đưa vào hàng huấn luyện lại.",
            )
          }
          iconLeading={
            pendingAction === "reindex" ? (
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <RefreshCw className="size-4" />
            )
          }
          className="tt-btn-touch uu-scope rounded-[9px]"
        >
          {pendingAction === "reindex" ? "Đang xếp hàng…" : "Huấn luyện lại"}
        </Button>
        <Button
          type="button"
          color="secondary"
          data-slot="button"
          isDisabled={pendingAction !== null}
          onClick={() =>
            run(
              "download",
              () =>
                downloadKnowledgeRawFile(
                  String(source.id),
                  source.file_name || "knowledge-source.md",
                ),
              "Đã tải tệp gốc.",
              false,
            )
          }
          iconLeading={
            pendingAction === "download" ? (
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <Download className="size-4" />
            )
          }
          className="tt-btn-touch uu-scope rounded-[9px]"
        >
          {pendingAction === "download" ? "Đang tải…" : "Tải tệp gốc"}
        </Button>
        <Dropdown.Root>
          <Button
            color="secondary"
            size="md"
            data-slot="button"
            isDisabled={pendingAction !== null}
            iconLeading={MoreHorizontal}
            aria-label={`Mở thao tác cho ${source.file_name}`}
            className="tt-btn-touch uu-scope rounded-[9px]"
          />
          <Dropdown.Popover placement="bottom end" className="uu-scope w-44">
            <Dropdown.Menu onAction={handleDetailAction}>
              <Dropdown.Item
                id="archive"
                icon={Archive}
                label="Lưu trữ"
                isDisabled={pendingAction !== null}
              />
              <Dropdown.Separator />
              <Dropdown.Item
                id="delete"
                icon={Trash2}
                isDisabled={deletePending}
              >
                <span className="text-error-primary">Xóa</span>
              </Dropdown.Item>
            </Dropdown.Menu>
          </Dropdown.Popover>
        </Dropdown.Root>
      </div>

      {processing && <PipelineMiniProgress source={source} />}

      {source.error && (
        <div className="rounded-[10px] border border-[var(--kb-rust-soft)] bg-[var(--kb-rust-soft)] p-3 text-body text-[var(--kb-rust)]">
          {source.error}
        </div>
      )}

      {/* Compact stat trio (units / flagged / updated) — hairline grid */}
      <div className="knowledge-detail-stats grid grid-cols-3 gap-px overflow-hidden border-y border-border bg-border">
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
      <div className="knowledge-digest-section">
        <h4 className="kb-display text-card-title text-foreground">
          {isCanonicalSource(source) ? "Tóm tắt nguồn" : "Tóm tắt digest"}
        </h4>
        {source.digest_summary ? (
          <div className="mt-2 border-l-2 border-[var(--kb-line-strong)] py-1 pl-3">
            <p className="text-body italic leading-6 text-[var(--kb-ink-700)] [font-family:var(--kb-font-display)]">
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
      <div className="knowledge-pipeline-section">
        <button
          type="button"
          onClick={() => setShowPipeline((value) => !value)}
          className="knowledge-pipeline-toggle flex w-full items-center justify-between gap-2 text-left text-button font-semibold text-foreground transition-colors hover:text-[var(--kb-teal)]"
          aria-expanded={showPipeline}
        >
          <span>Chi tiết pipeline (6 bước)</span>
          <span className="kb-mono text-helper text-muted-foreground">
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
          <div className="knowledge-pipeline-body">
            <p className="mb-3 text-helper leading-5 text-muted-foreground">
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
    <div className="kb-mono text-badge font-semibold uppercase tracking-[0.08em] text-muted-foreground">
      {label}
    </div>
    <div className="kb-mono mt-1.5 break-words text-subsection font-semibold text-foreground">
      {value}
    </div>
  </div>
);

const PipelineDigestHint = ({ source }: { source: KnowledgeSource }) => {
  if (isRunning(source)) {
    return (
      <div className="mt-2 flex items-center gap-2 rounded-[10px] bg-[var(--kb-teal-soft)] p-3 text-body text-[var(--kb-teal)]">
        <RefreshCw className="size-4 animate-spin motion-reduce:animate-none" />
        {isCanonicalSource(source)
          ? "Đang chuẩn hóa Markdown và tạo đơn vị truy xuất."
          : "Đang xử lý trong pipeline. Tóm tắt sẽ xuất hiện sau khi digest hoàn tất."}
      </div>
    );
  }

  if (isFailed(source)) {
    return (
      <div className="mt-2 rounded-[10px] bg-[var(--kb-rust-soft)] p-3 text-body text-[var(--kb-rust)]">
        Pipeline đã lỗi trước khi tạo tóm tắt. Huấn luyện lại hoặc kiểm tra định
        dạng nguồn nếu lỗi lặp lại.
      </div>
    );
  }

  return (
    <div className="mt-2 border-l-2 border-[var(--kb-line-strong)] py-1 pl-3">
      <p className="text-body italic leading-6 text-[var(--kb-ink-300)] [font-family:var(--kb-font-display)]">
        Chưa có tóm tắt. Nội dung sẽ xuất hiện sau khi xử lý.
      </p>
    </div>
  );
};
