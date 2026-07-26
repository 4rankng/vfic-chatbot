import { useState } from "react";
import { Copy, Eye, EyeOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import {
  SettingsFieldStatus,
  type SettingsStatusState,
} from "./SettingsFieldStatus";
import type { SecretStatus } from "./api";

export type CredentialFieldNotify = (
  message: string,
  options: { type: "success" | "error" },
) => void;

export const copyCredentialFieldValue = async (
  label: string,
  value: string,
  notify: CredentialFieldNotify,
) => {
  try {
    if (!navigator.clipboard?.writeText) {
      throw new Error("Clipboard unavailable");
    }
    await navigator.clipboard.writeText(value);
    notify(`Đã sao chép ${label}.`, { type: "success" });
  } catch {
    notify(`Không thể sao chép ${label}.`, { type: "error" });
  }
};

export const CredentialSecretField = ({
  id,
  label,
  status,
  statusState = "ready",
  value,
  placeholder,
  onValueChange,
  notify,
  copyValue = copyCredentialFieldValue,
}: {
  id: string;
  label: string;
  status: SecretStatus;
  statusState?: SettingsStatusState;
  value: string;
  placeholder: string;
  onValueChange: (value: string) => void;
  notify: CredentialFieldNotify;
  copyValue?: typeof copyCredentialFieldValue;
}) => {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <div className="settings-field">
      <div className="settings-field-label-row">
        <Label htmlFor={id}>{label}</Label>
        <SettingsFieldStatus
          configured={status.configured}
          state={statusState}
        />
      </div>
      <div className="settings-sensitive-input">
        <Input
          id={id}
          type={isVisible ? "text" : "password"}
          autoComplete="off"
          value={value}
          placeholder={
            status.preview ? `Hiện tại: ${status.preview}` : placeholder
          }
          className="settings-input"
          onChange={(event) => onValueChange(event.target.value)}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="settings-input-action"
          aria-label={isVisible ? `Ẩn ${label}` : `Hiện ${label}`}
          onClick={() => setIsVisible((visible) => !visible)}
        >
          {isVisible ? <EyeOff /> : <Eye />}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="settings-input-action"
          aria-label={`Sao chép ${label}`}
          disabled={!value}
          onClick={() => void copyValue(label, value, notify)}
        >
          <Copy />
        </Button>
      </div>
    </div>
  );
};
