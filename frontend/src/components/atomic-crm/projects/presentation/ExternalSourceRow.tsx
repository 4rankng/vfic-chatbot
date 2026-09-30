import { Loader2, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  formatCompactTimestamp,
  formatTimestamp,
  statusDotClass,
  statusErrorClass,
  truncate,
  type ExternalSourceRowState,
} from "../domain/externalSourceRow";
import { singlePageSyncErrorMessage } from "../project-knowledge-service";

const STATUS_LABEL: Record<string, string> = {
  NEW: "Chưa đồng bộ",
  PROCESSING: "Đang đồng bộ",
  OK: "Đã đồng bộ",
  NO_OP: "Không thay đổi",
  FAILED: "Lỗi đồng bộ",
};

type Props = {
  row: ExternalSourceRowState;
  isSinglePage: boolean;
  /** Show the "Đồng bộ" / "Xóa" actions at all. */
  mutable: boolean;
  disabled?: boolean;
  /** A run-now request for this row is in flight. */
  processing?: boolean;
  /** The 5-minute run-now cooldown for this row is active. */
  coolingDown?: boolean;
  onRunNow: (row: ExternalSourceRowState) => void;
  onRemove: (row: ExternalSourceRowState) => void;
};

/**
 * One configured external source: identity, auto-sync state, last sync result
 * and the per-row actions. Presentational only — the list owns loading and
 * polling.
 */
export const ExternalSourceRow = ({
  row,
  isSinglePage,
  mutable,
  disabled,
  processing,
  coolingDown,
  onRunNow,
  onRemove,
}: Props) => {
  const autoDisabled = row.last_status === "FAILED" && !row.auto_sync_enabled;
  // The name column truncates with an ellipsis, so the full value must stay
  // reachable for pointer and screen-reader users alike (the URL line below
  // does the same).
  const name =
    "category_key" in row && row.category_key
      ? row.category_key
      : `gid=${row.sheet_gid}`;

  return (
    <div className="project-external-source-row">
      <div className="project-external-source-identity">
        <div className="project-external-source-heading">
          <p className="project-external-source-name" title={name}>
            {name}
          </p>
        </div>
        <p className="project-external-source-url" title={row.sheet_url}>
          {truncate(row.sheet_url)}
        </p>
      </div>

      <div className="project-external-source-sync">
        <div className="project-external-source-status-line">
          <span
            className={cn(
              "project-external-source-status-dot",
              statusDotClass(row),
            )}
            aria-hidden="true"
          />
          <span className="project-external-source-status-label">
            {STATUS_LABEL[row.last_status] ?? row.last_status}
          </span>
          {row.auto_sync_enabled ? (
            <Badge
              variant="secondary"
              title="Tự động mỗi ngày"
              aria-label="Tự động mỗi ngày"
              className="project-external-source-schedule"
            >
              <RefreshCw className="size-3" aria-hidden="true" />
              24h
            </Badge>
          ) : (
            <Badge variant="outline">Thủ công</Badge>
          )}
          {autoDisabled && <Badge variant="destructive">Đã tắt lịch</Badge>}
        </div>
        <div
          className={cn("project-external-source-meta", statusErrorClass(row))}
        >
          <span
            className="project-external-source-meta-item"
            title={`Đồng bộ gần nhất: ${formatTimestamp(row.last_synced_at)}`}
            aria-label={`Đồng bộ gần nhất: ${formatTimestamp(row.last_synced_at)}`}
          >
            <time dateTime={row.last_synced_at ?? undefined}>
              {formatCompactTimestamp(row.last_synced_at)}
            </time>
          </span>
          {typeof row.last_row_count === "number" ? (
            <span
              className="project-external-source-meta-item project-external-source-row-count"
              aria-label={`${row.last_row_count} hàng`}
              title={`${row.last_row_count} hàng đã đồng bộ`}
            >
              {row.last_row_count} hàng
            </span>
          ) : null}
          {row.last_status === "FAILED" && row.last_error ? (
            <span className="project-external-source-error">
              {isSinglePage
                ? singlePageSyncErrorMessage(row.last_error)
                : row.last_error}
            </span>
          ) : null}
        </div>
      </div>

      {mutable && (
        <div className="project-external-source-actions">
          <Button
            type="button"
            size="sm"
            aria-label="Đồng bộ ngay"
            onClick={() => onRunNow(row)}
            disabled={disabled || processing || coolingDown}
            title={
              coolingDown
                ? "Vui lòng đợi 5 phút giữa các lần đồng bộ"
                : undefined
            }
            className="project-external-source-sync-button"
          >
            {processing ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            Đồng bộ
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="project-source-delete"
            onClick={() => onRemove(row)}
            disabled={disabled}
            aria-label="Xóa nguồn đồng bộ"
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
};
