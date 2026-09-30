import { PROJECT_KNOWLEDGE_CATEGORY_LABELS } from "../domain/project-knowledge-policy";
import type { IngestItemState } from "./use-project-ingest";

const STATUS_LABEL: Record<IngestItemState["status"], string> = {
  pending: "Chờ nạp",
  writing: "Đang nạp",
  queued: "Đang chờ xử lý",
  processing: "Đang xử lý",
  active: "Đã nạp",
  failed: "Không thành công",
};

const STATUS_CLASS: Record<IngestItemState["status"], string> = {
  pending: "text-muted-foreground",
  writing: "text-foreground",
  queued: "text-muted-foreground",
  processing: "text-foreground",
  active: "text-foreground",
  failed: "text-destructive",
};

const MARK: Record<IngestItemState["status"], string> = {
  pending: "○",
  writing: "•",
  queued: "◐",
  processing: "◐",
  active: "●",
  failed: "×",
};

export type IngestProgressBoardProps = Readonly<{
  items: readonly IngestItemState[];
  slow?: boolean;
}>;

/**
 * Live status for every category in a brief ingest. A row shows "Đã nạp"
 * exactly when the backend catalog reports the revision as the category's
 * active revision — the board never invents progress.
 */
export const IngestProgressBoard = ({
  items,
  slow = false,
}: IngestProgressBoardProps) => (
  <ul role="list" className="m-0 flex list-none flex-col gap-1 p-0">
    {items.map((item) => (
      <li
        key={item.key}
        className="flex items-center justify-between gap-3 text-helper"
      >
        <span className="flex items-center gap-2">
          <span aria-hidden="true">{MARK[item.status]}</span>
          <span className="text-foreground">
            {PROJECT_KNOWLEDGE_CATEGORY_LABELS[item.key]}
          </span>
        </span>
        <span className={STATUS_CLASS[item.status]}>
          {STATUS_LABEL[item.status]}
          {slow && (item.status === "queued" || item.status === "processing")
            ? " — hệ thống đang bận, vẫn đang xử lý"
            : ""}
        </span>
      </li>
    ))}
  </ul>
);
