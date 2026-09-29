import { type ReactNode } from "react";
import type { Key } from "react-aria-components";
import { useDeleteWithUndoController, useRedirect, useRefresh } from "ra-core";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { Dropdown } from "@/components/base/dropdown/dropdown";
import { ProgressBarBase } from "@/components/base/progress-indicators/progress-indicators";
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

const STAMP_COLORS = {
  ready: "success",
  error: "error",
  pending: "warning",
  processing: "brand",
} as const;

const Stamp = ({
  tone,
  icon,
  children,
}: {
  tone: keyof typeof STAMP_COLORS;
  icon?: ReactNode;
  children: ReactNode;
}) => (
  <Badge
    type="pill-color"
    size="sm"
    color={STAMP_COLORS[tone]}
    className="gap-1 uppercase tracking-wide"
  >
    {icon}
    {children}
  </Badge>
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
      <ProgressBarBase
        value={percent}
        className="mt-1.5 h-1.5 rounded-full bg-[var(--kb-line-strong)]/40!"
        progressClassName={cn(
          "rounded-full",
          isFailed(source) ? "bg-[var(--kb-rust)]!" : "bg-[var(--kb-teal)]!",
        )}
      />
    </div>
  );
};

const CHIP_COLORS = {
  neutral: "gray",
  success: "success",
  warning: "warning",
  danger: "error",
  processing: "brand",
} as const;

export const Chip = ({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: keyof typeof CHIP_COLORS;
}) => (
  <Badge type="pill-color" size="sm" color={CHIP_COLORS[tone]}>
    {children}
  </Badge>
);

const SourceRowActions = ({ source }: { source: KnowledgeSource }) => {
  const redirect = useRedirect();
  const refresh = useRefresh();
  const { isPending, handleDelete } = useDeleteWithUndoController({
    record: source,
    resource: "knowledge_sources",
    redirect: false,
    successMessage: "Đã xóa tài liệu.",
    mutationOptions: { onSuccess: () => refresh() },
  });

  const handleAction = (key: Key) => {
    if (key === "edit") redirect("edit", "knowledge_sources", source.id);
    if (key === "delete") handleDelete(undefined as never);
  };

  return (
    <Dropdown.Root>
      <Button
        color="tertiary"
        size="sm"
        data-slot="button"
        className="uu-scope size-11 rounded-lg text-muted-foreground opacity-70 transition-opacity hover:opacity-100"
        iconLeading={MoreHorizontal}
        aria-label={`Mở thao tác cho ${source.file_name}`}
      />
      <Dropdown.Popover placement="bottom end" className="uu-scope w-40">
        <Dropdown.Menu onAction={handleAction}>
          <Dropdown.Item id="edit" icon={Pencil} label="Sửa" />
          <Dropdown.Separator />
          <Dropdown.Item
            id="delete"
            icon={Trash2}
            isDisabled={isPending}
            aria-label="Xóa"
          >
            <span className="text-error-primary">Xóa</span>
          </Dropdown.Item>
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown.Root>
  );
};
