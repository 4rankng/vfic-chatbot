import { AlertCircle, CheckCircle2 } from "lucide-react";

export const SettingsFieldStatus = ({
  configured,
}: {
  configured: boolean;
}) => {
  const label = configured ? "Đã lưu" : "Chưa cấu hình";
  const Icon = configured ? CheckCircle2 : AlertCircle;

  return (
    <span
      className={`settings-field-status${configured ? " is-configured" : ""}`}
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
}: {
  configured: number;
  total: number;
  disabled?: boolean;
}) => {
  const ready = configured === total;
  const label = disabled
    ? "Đang tắt"
    : `${configured}/${total} trường đã cấu hình`;
  const Icon = ready ? CheckCircle2 : AlertCircle;

  return (
    <span
      className={`settings-group-status ${
        disabled ? "is-off" : ready ? "is-ready" : "is-incomplete"
      }`}
      aria-label={label}
      title={label}
    >
      {disabled ? null : <Icon aria-hidden="true" />}
      {disabled ? "Tắt" : `${configured}/${total}`}
    </span>
  );
};
