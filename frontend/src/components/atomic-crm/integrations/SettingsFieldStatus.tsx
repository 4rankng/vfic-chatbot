import {
  AlertCircle,
  CheckCircle2,
  CircleHelp,
  LoaderCircle,
} from "lucide-react";

import { Badge } from "@/components/base/badges/badges";

export type SettingsStatusState = "ready" | "loading" | "error";

/**
 * The per-field marker beside a credential label. It stays a bare 20px icon
 * rather than a Untitled UI badge on purpose: it reports one field's state, and
 * the console's layout contract measures it as a 20px square so it cannot read
 * as a pill badge in the middle of a form row.
 */
export const SettingsFieldStatus = ({
  configured,
  state = "ready",
}: {
  configured: boolean;
  state?: SettingsStatusState;
}) => {
  const label =
    state === "loading"
      ? "Đang tải trạng thái"
      : state === "error"
        ? "Không thể tải trạng thái"
        : configured
          ? "Đã lưu"
          : "Chưa cấu hình";
  const Icon =
    state === "loading"
      ? LoaderCircle
      : state === "error"
        ? CircleHelp
        : configured
          ? CheckCircle2
          : AlertCircle;

  return (
    <span
      className={`settings-field-status${
        state !== "ready" ? ` is-${state}` : configured ? " is-configured" : ""
      }`}
      role="img"
      aria-label={label}
      title={label}
    >
      <Icon aria-hidden="true" />
    </span>
  );
};

/**
 * The per-group "how much of this is configured" chip: a Untitled UI pill whose
 * colour carries the state, over the same `x/y` counter and screen-reader
 * sentence the console already reported.
 */
export const SettingsGroupStatus = ({
  configured,
  total,
  disabled = false,
  state = "ready",
}: {
  configured: number;
  total: number;
  disabled?: boolean;
  state?: SettingsStatusState;
}) => {
  const ready = configured === total;
  const label =
    state === "loading"
      ? "Đang tải cấu hình"
      : state === "error"
        ? "Không thể tải cấu hình"
        : disabled
          ? "Đang tắt"
          : `${configured}/${total} trường đã cấu hình`;
  const Icon =
    state === "loading"
      ? LoaderCircle
      : state === "error"
        ? CircleHelp
        : ready
          ? CheckCircle2
          : AlertCircle;
  const shortLabel =
    state === "loading"
      ? "…"
      : state === "error"
        ? "Lỗi"
        : disabled
          ? "Tắt"
          : `${configured}/${total}`;
  const color =
    state === "loading"
      ? "gray"
      : state === "error"
        ? "error"
        : disabled
          ? "gray"
          : ready
            ? "success"
            : "warning";

  return (
    <span title={label}>
      <Badge
        type="pill-color"
        size="sm"
        color={color}
        className="settings-group-status uu-scope gap-1"
      >
        {disabled && state === "ready" ? null : (
          <Icon aria-hidden="true" className="size-4 shrink-0" />
        )}
        <span aria-hidden="true">{shortLabel}</span>
        <span className="sr-only">{label}</span>
      </Badge>
    </span>
  );
};
