import { useState } from "react";
import { Link } from "react-router";
import { useTranslate } from "ra-core";
import { Bell, Reply, TriangleAlert, RefreshCw } from "lucide-react";
import { Dialog, DialogTrigger } from "react-aria-components";

import { Badge } from "@/components/base/badges/badges";
import { Button } from "@/components/base/buttons/button";
import { Dropdown } from "@/components/base/dropdown/dropdown";

import { conversationChannelLabel } from "../../types";
import { formatElapsed } from "../../dashboard/attentionDashboard";
import { useNeedsAttention, type NeedsAttentionRow } from "./useNeedsAttention";
import { PushNotificationsToggle } from "../../notifications/PushNotificationsToggle";

const INBOX_DESTINATION = "/conversations?needs_attention=true";

const rowDestination = (id: string) => `/conversations?id=${id}`;

const rowTitle = (row: NeedsAttentionRow): string =>
  row.contact?.display_name?.trim() || "Ứng viên ẩn danh";

export type NotificationsMenuProps = {
  /** Total unread count from the always-mounted {@link useNotifications} hook. */
  count: number;
};

/**
 * Topbar notification bell. The panel is a React Aria popover so its rows can
 * carry Untitled UI link and badge primitives without mixing in the Radix
 * layer; the row query only mounts while the panel is open.
 */
export const NotificationsMenu = ({ count }: NotificationsMenuProps) => {
  const [open, setOpen] = useState(false);
  const { rows, total, isLoading, isError, refetch } = useNeedsAttention(open);
  const translate = useTranslate();

  const triggerLabel =
    count > 0 ? `${count} cuộc trò chuyện cần chú ý` : "Không có thông báo mới";

  return (
    <DialogTrigger isOpen={open} onOpenChange={setOpen}>
      <Button
        color="tertiary"
        size="md"
        iconLeading={Bell}
        aria-label={triggerLabel}
        className="rounded-lg"
      >
        {count > 0 ? (
          <Badge size="sm" type="pill-color" color="error">
            {count > 99 ? "99+" : count}
          </Badge>
        ) : null}
      </Button>
      <Dropdown.Popover
        placement="bottom end"
        className="uu-scope w-90 max-w-[90vw]"
      >
        <Dialog aria-label="Thông báo" className="outline-hidden">
          <div className="flex items-center gap-3 border-b border-secondary px-4 py-3">
            <div className="flex min-w-0 flex-col">
              <span className="text-sm font-semibold text-primary">
                Thông báo
              </span>
              <span className="text-xs text-tertiary">
                {count > 0
                  ? `${count} hội thoại cần phản hồi`
                  : "Không có thông báo mới"}
              </span>
            </div>
            {total > 0 ? (
              <Badge
                size="sm"
                type="pill-color"
                color="error"
                className="ml-auto"
              >
                {total > 99 ? "99+" : total}
              </Badge>
            ) : null}
          </div>

          <div className="max-h-96 min-h-24 overflow-y-auto">
            {isError ? (
              <div className="flex flex-col items-center gap-3 px-4 py-8 text-center">
                <TriangleAlert
                  aria-hidden="true"
                  className="size-5 text-fg-error-secondary"
                />
                <span className="text-sm text-secondary">
                  Không tải được thông báo.
                </span>
                <Button
                  color="secondary"
                  size="sm"
                  iconLeading={RefreshCw}
                  onPress={() => void refetch()}
                >
                  {translate("crm.common.retry")}
                </Button>
              </div>
            ) : isLoading ? (
              <ul className="flex flex-col gap-1 p-2" aria-hidden>
                {[0, 1, 2].map((index) => (
                  <li
                    key={index}
                    className="h-14 animate-pulse rounded-lg bg-secondary"
                  />
                ))}
              </ul>
            ) : rows.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
                <Bell
                  aria-hidden="true"
                  className="size-5 text-fg-quaternary"
                />
                <span className="text-sm text-tertiary">
                  Không có thông báo mới.
                </span>
              </div>
            ) : (
              <ul className="flex flex-col p-1">
                {rows.map((row) => {
                  const elapsed = row.last_inbound_at
                    ? formatElapsed(row.last_inbound_at)
                    : "";
                  return (
                    <li key={row.id}>
                      <Link
                        to={rowDestination(row.id)}
                        onClick={() => setOpen(false)}
                        className="flex w-full items-start gap-3 rounded-lg px-3 py-2.5 outline-focus-ring transition hover:bg-primary_hover focus-visible:outline-2 focus-visible:outline-offset-2"
                      >
                        <span
                          aria-hidden="true"
                          className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-fg-quaternary"
                        >
                          <Reply className="size-4" />
                        </span>
                        <span className="flex min-w-0 flex-col">
                          <span className="truncate text-sm font-semibold text-primary">
                            {rowTitle(row)}
                          </span>
                          <span className="flex items-center gap-1.5 text-xs text-tertiary">
                            <span>
                              {conversationChannelLabel(
                                row.channel_identity?.provider,
                              )}
                            </span>
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

          <div className="flex items-center justify-between gap-3 border-t border-secondary px-4 py-2.5">
            <Link
              to={INBOX_DESTINATION}
              onClick={() => setOpen(false)}
              className="text-sm font-semibold text-brand-secondary outline-focus-ring hover:text-brand-secondary_hover focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              Xem tất cả trong Hộp thư
            </Link>
            <PushNotificationsToggle />
          </div>
        </Dialog>
      </Dropdown.Popover>
    </DialogTrigger>
  );
};
