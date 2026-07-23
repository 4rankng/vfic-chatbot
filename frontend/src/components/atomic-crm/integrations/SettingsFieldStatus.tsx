import {
  AlertCircle,
  CheckCircle2,
  CircleHelp,
  LoaderCircle,
} from "lucide-react";

export type SettingsStatusState = "ready" | "loading" | "error";

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
        state !== "ready"
          ? ` is-${state}`
          : configured
            ? " is-configured"
            : ""
      }`}
      role="img"
      aria-label={label}
      title={label}
    >
      <Icon aria-hidden="true" />
    </span>
  );
};

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

  return (
    <span
      className={`settings-group-status ${
        state !== "ready"
          ? `is-${state}`
          : disabled
            ? "is-off"
            : ready
              ? "is-ready"
              : "is-incomplete"
      }`}
      title={label}
    >
      {disabled && state === "ready" ? null : <Icon aria-hidden="true" />}
      <span aria-hidden="true">{shortLabel}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
};
