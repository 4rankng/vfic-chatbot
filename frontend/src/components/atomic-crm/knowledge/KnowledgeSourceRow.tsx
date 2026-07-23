import { type ReactNode } from "react";
import { useRedirect, useRefresh } from "ra-core";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
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
import { cn, getRelativeTimeString } from "@/lib/utils";
import type { KnowledgeSource, Project } from "../types";
import { stageLabel } from "./stageTone";
import {
  flaggedCount,
  isCanonicalSource,
  isFailed,
  isProcessing,
  isPossiblyStuck,
  isPublished,
  isRunning,
  needsReview,
  pipelinePercent,
  sourceStage,
} from "./knowledgePipelineUtils";
export const KnowledgeSourceRow = ({
  source,
  project,
  selected,
  onSelect,
}: {
  source: KnowledgeSource;
  project?: Project;
  selected: boolean;
  onSelect: () => void;
}) => {
  const flags = flaggedCount(source);
  const processing = isProcessing(source);

  return (
    <article
      role="listitem"
      className={cn(
        "knowledge-source-row group flex items-stretch border-b border-border transition-colors",
        selected
          ? "bg-[var(--kb-teal-soft)] shadow-[inset_2.5px_0_0_0_var(--kb-teal)]"
          : "hover:bg-secondary",
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        aria-controls="knowledge-source-detail"
        aria-label={`Xem ${source.file_name}`}
        className="knowledge-source-row-main flex min-h-11 min-w-0 flex-1 gap-3 px-4 pb-3 pt-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <div
              className="min-w-0 truncate text-body-sm font-semibold text-foreground"
              title={source.file_name}
            >
              {source.file_name}
            </div>
            <div className="shrink-0 pt-0.5">
              <SourceStamp source={source} />
            </div>
          </div>
          <div className="kb-mono mt-1 truncate text-caption text-muted-foreground">
            {project?.name ?? source.project_name ?? "Chưa gắn dự án"} ·{" "}
            {getRelativeTimeString(source.updated_at ?? source.created_at)} ·{" "}
            {source.digest_meta?.unit_count ?? 0} đơn vị
          </div>

          {processing && (
            <div className="mt-3">
              <PipelineMiniProgress source={source} />
            </div>
          )}

          {flags > 0 && (
            <div className="mt-2">
              <Chip tone="warning">{flags} cần xem lại</Chip>
            </div>
          )}
        </div>
      </button>

      {(flags > 0 || selected) && (
        <div className="flex shrink-0 items-center border-l border-border px-1">
          <SourceRowActions source={source} />
        </div>
      )}
    </article>
  );
};

const Stamp = ({
  tone,
  icon,
  children,
}: {
  tone: "ready" | "error" | "pending" | "processing";
  icon?: ReactNode;
  children: ReactNode;
}) => (
  <span
    className={cn(
      "kb-stamp",
      tone === "ready" && "text-[var(--kb-teal)]",
      tone === "error" && "text-[var(--kb-rust)]",
      tone === "pending" && "kb-stamp--pending text-[var(--kb-ochre)]",
      tone === "processing" && "text-[var(--kb-teal)]",
    )}
  >
    {icon}
    {children}
  </span>
);

export const SourceStamp = ({ source }: { source: KnowledgeSource }) => {
  if (isFailed(source))
    return (
      <Stamp tone="error" icon={<AlertTriangle className="size-3" />}>
        Lỗi
      </Stamp>
    );
  if (isPossiblyStuck(source))
    return (
      <Stamp tone="pending" icon={<RefreshCw className="size-3" />}>
        Chờ worker
      </Stamp>
    );
  if (isRunning(source))
    return (
      <Stamp
        tone="processing"
        icon={
          <RefreshCw className="size-3 animate-spin motion-reduce:animate-none" />
        }
      >
        Đang xử lý
      </Stamp>
    );
  if (isPublished(source))
    return (
      <Stamp tone="ready" icon={<CheckCircle2 className="size-3" />}>
        Sẵn sàng
      </Stamp>
    );
  if (needsReview(source)) return <Stamp tone="pending">Cần xem lại</Stamp>;
  return (
    <Stamp tone="pending">
      {stageLabel(sourceStage(source), {
        isCanonical: isCanonicalSource(source),
      })}
    </Stamp>
  );
};

// Slim transient progress — only mounted while a source is actively processing.
export const PipelineMiniProgress = ({
  source,
}: {
  source: KnowledgeSource;
}) => {
  const percent = pipelinePercent(source);
  return (
    <div className="min-w-0">
      <div className="kb-mono flex items-center justify-between gap-2 text-caption">
        <span className="font-semibold text-[var(--kb-teal)]">
          {isPossiblyStuck(source)
            ? "Đang chờ worker"
            : isPublished(source)
              ? "Sẵn sàng trả lời"
              : stageLabel(sourceStage(source), {
                  isCanonical: isCanonicalSource(source),
                })}
        </span>
        <span className="text-muted-foreground">{percent}%</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[var(--kb-line-strong)]/40">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            isFailed(source) ? "bg-[var(--kb-rust)]" : "bg-[var(--kb-teal)]",
          )}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
};

export const Chip = ({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger" | "processing";
}) => (
  <span
    className={cn(
      "kb-mono rounded-full px-2 py-1 text-caption font-semibold leading-none",
      tone === "neutral" && "bg-secondary text-[var(--kb-ink-700)]",
      tone === "success" && "bg-[var(--kb-teal-soft)] text-[var(--kb-teal)]",
      tone === "warning" && "bg-[var(--kb-ochre-soft)] text-[var(--kb-ochre)]",
      tone === "danger" && "bg-[var(--kb-rust-soft)] text-[var(--kb-rust)]",
      tone === "processing" && "bg-[var(--kb-teal-soft)] text-[var(--kb-teal)]",
    )}
  >
    {children}
  </span>
);

const SourceRowActions = ({ source }: { source: KnowledgeSource }) => {
  const redirect = useRedirect();
  const refresh = useRefresh();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-11 rounded-lg text-muted-foreground opacity-70 transition-opacity hover:opacity-100"
          aria-label={`Mở thao tác cho ${source.file_name}`}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuItem
          onSelect={() => redirect("edit", "knowledge_sources", source.id)}
        >
          <Pencil className="size-4" />
          Sửa
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
          className="h-11 w-full justify-start px-2 text-button text-destructive hover:bg-destructive/10"
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
