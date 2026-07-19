import { useState } from "react";
import { Bell, Reply, RefreshCw, AlertCircle } from "lucide-react";
import { Link } from "react-router";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { formatElapsed } from "../../dashboard/attentionDashboard";
import { useNeedsAttention, type NeedsAttentionRow } from "./useNeedsAttention";

const INBOX_DESTINATION = "/conversations?needs_attention=true";

/** Vietnamese channel label for the masked provider tag on each row. */
const channelLabel = (provider: string | undefined): string => {
  switch (provider) {
    case "zalo_bot":
      return "Zalo Chatbot";
    case "zalo_oa":
      return "Zalo OA";
    case "facebook_messenger":
      return "Messenger";
    default:
      return provider ? provider : "Kênh";
  }
};

const rowDestination = (id: string) => `/conversations?id=${id}`;

const rowTitle = (row: NeedsAttentionRow): string =>
  row.contact?.display_name?.trim() || "Ứng viên ẩn danh";

export type NotificationsPopoverProps = {
  /** Total unread count from the always-mounted {@link useNotifications} hook. */
  count: number;
};

export const NotificationsPopover = ({ count }: NotificationsPopoverProps) => {
  const [open, setOpen] = useState(false);
  const { rows, total, isLoading, isError, refetch } = useNeedsAttention(open);

  const triggerLabel =
    count > 0
      ? `${count} cuộc trò chuyện cần chú ý`
      : "Không có thông báo mới";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="workspace-topbar-notifications tt-btn tt-btn-ghost tt-btn-circle"
          aria-label={triggerLabel}
          aria-haspopup="dialog"
        >
          <Bell aria-hidden="true" />
          {count > 0 ? (
            <span className="workspace-topbar-badge tt-badge tt-badge-error tt-badge-xs">
              {count > 99 ? "99+" : count}
            </span>
          ) : null}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        role="dialog"
        aria-label="Thông báo"
        className={cn(
          "workspace-notifications-popover w-[min(360px,calc(100vw-1.5rem))] p-0",
        )}
      >
        {/* Header: Tailkit a-c-dropdowns-03 profile header, adapted to a bell + title + count chip. */}
        <div className="workspace-notifications-header">
          <span
            className="workspace-notifications-header-icon"
            aria-hidden="true"
          >
            <Bell />
          </span>
          <div className="workspace-notifications-header-text">
            <span className="workspace-notifications-title">Thông báo</span>
            <span className="workspace-notifications-subtitle">
              {count > 0
                ? `${count} hội thoại cần phản hồi`
                : "Không có thông báo mới"}
            </span>
          </div>
          {total > 0 ? (
            <span className="tt-badge tt-badge-error tt-badge-xs workspace-notifications-header-badge">
              {total > 99 ? "99+" : total}
            </span>
          ) : null}
        </div>

        {/* Body */}
        <div className="workspace-notifications-body">
          {isError ? (
            <div className="workspace-notifications-empty">
              <AlertCircle aria-hidden="true" />
              <span>Không tải được thông báo.</span>
              <button
                type="button"
                className="tt-btn tt-btn-ghost tt-btn-sm"
                onClick={() => void refetch()}
              >
                <RefreshCw aria-hidden="true" />
                Thử lại
              </button>
            </div>
          ) : isLoading ? (
            <NotificationRowSkeleton />
          ) : rows.length === 0 ? (
            <div className="workspace-notifications-empty">
              <Bell aria-hidden="true" />
              <span>Không có thông báo mới.</span>
            </div>
          ) : (
            <ul className="workspace-notifications-list">
              {rows.map((row) => {
                const elapsed = row.last_inbound_at
                  ? formatElapsed(row.last_inbound_at)
                  : "";
                return (
                  <li key={row.id}>
                    <Link
                      to={rowDestination(row.id)}
                      onClick={() => setOpen(false)}
                      className="workspace-notifications-item"
                    >
                      <span
                        className="workspace-notifications-item-icon"
                        aria-hidden="true"
                      >
                        <Reply />
                      </span>
                      <span className="workspace-notifications-item-body">
                        <span className="workspace-notifications-item-title">
                          {rowTitle(row)}
                        </span>
                        <span className="workspace-notifications-item-meta">
                          <span>{channelLabel(row.channel_identity?.provider)}</span>
                          {elapsed ? (
                            <>
                              <span aria-hidden="true">·</span>
                              <span>{elapsed}</span>
                            </>
                          ) : null}
                        </span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Footer: see-all link to the full needs-attention inbox. */}
        <div className="workspace-notifications-footer">
          <Link
            to={INBOX_DESTINATION}
            onClick={() => setOpen(false)}
            className="workspace-notifications-footer-link"
          >
            Xem tất cả trong Hộp thư
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  );
};

const NotificationRowSkeleton = () => (
  <ul className="workspace-notifications-list" aria-hidden>
    {[0, 1, 2].map((i) => (
      <li key={i}>
        <div className="workspace-notifications-item workspace-notifications-item--skeleton">
          <Skeleton
            shimmer
            className="!rounded-full tt-skeleton workspace-notifications-skeleton-icon"
          />
          <div className="workspace-notifications-skeleton-body">
            <Skeleton shimmer className="workspace-notifications-skeleton-line-1" />
            <Skeleton shimmer className="workspace-notifications-skeleton-line-2" />
          </div>
        </div>
      </li>
    ))}
  </ul>
);
