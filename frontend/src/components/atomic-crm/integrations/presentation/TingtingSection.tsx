import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useNotify, useTranslate } from "ra-core";

import { Button } from "@/components/ui/button";

import type { SettingsStatusState } from "../SettingsFieldStatus";
import { SettingsGroupStatus } from "../SettingsFieldStatus";
import {
  zaloIntegrationGateway,
  type TingtingSettings,
  type TingtingSettingsUpdate,
} from "../api";
import { SecretField } from "./SecretField";
import { SettingsGroup, SettingsSectionPanel } from "./SettingsGroup";

/** One query key for the endpoint, so a save can write back its own response. */
const tingtingSettingsKey = ["tingting-settings"] as const;

/**
 * The TingTing view: one deployment-wide API key for the password-reset API.
 * The key is sent as the `X-API-Key` header; the OTP workflow itself is built
 * into the backend, so the key is the only thing the operator configures.
 */
export const TingtingSection = () => {
  const notify = useNotify();
  const translate = useTranslate();
  const queryClient = useQueryClient();
  // Stored keys never enter form state: a blank field means "keep stored".
  const [apiKey, setApiKey] = useState("");

  const {
    data: settings,
    isPending,
    isError,
  } = useQuery<TingtingSettings>({
    queryKey: tingtingSettingsKey,
    queryFn: () => zaloIntegrationGateway.loadTingtingSettings(),
    staleTime: 30_000,
  });

  const statusState: SettingsStatusState = isPending
    ? "loading"
    : isError
      ? "error"
      : "ready";

  const saveSettings = useMutation<
    TingtingSettings,
    Error,
    TingtingSettingsUpdate
  >({
    mutationFn: (body) => zaloIntegrationGateway.saveTingtingSettings(body),
    onSuccess: (data) => {
      // Back to "keep stored": the response is the section's new truth.
      setApiKey("");
      queryClient.setQueryData(tingtingSettingsKey, data);
      notify("Đã lưu API key TingTing.", { type: "success" });
    },
    onError: () => {
      notify("Không thể lưu API key TingTing.", { type: "error" });
    },
  });

  // A blank field keeps the stored key, so there is nothing to send until the
  // operator types a new one.
  const trimmedApiKey = apiKey.trim();
  const configured = settings?.configured ?? false;

  const submit = () => {
    saveSettings.mutate({ api_key: trimmedApiKey });
  };

  return (
    <SettingsSectionPanel id="settings-tingting">
      <div className="settings-grid settings-grid-models">
        <SettingsGroup
          className="settings-llm-card"
          title="TingTing · Đặt lại mật khẩu"
          description="Tra cứu nhân sự và gửi OTP đặt lại mật khẩu qua API TingTing."
          icon={<KeyRound className="size-4" />}
          meta={
            <SettingsGroupStatus
              configured={configured ? 1 : 0}
              total={1}
              state={statusState}
            />
          }
        >
          <SecretField
            id="tingting_api_key"
            label="API key TingTing"
            placeholder="Nhập API key"
            configured={settings?.api_key.configured ?? false}
            statusState={statusState}
            preview={settings?.api_key.preview ?? null}
            value={apiKey}
            onChange={setApiKey}
            notify={notify}
            hint="Quy trình gửi OTP đã được tích hợp sẵn trong hệ thống. Để trống để giữ API key đã lưu."
          />
        </SettingsGroup>
      </div>

      <div className={`settings-llm-footer${trimmedApiKey ? " is-dirty" : ""}`}>
        <Button
          type="button"
          className="settings-primary-action tt-btn-touch"
          onClick={submit}
          disabled={!trimmedApiKey || saveSettings.isPending}
        >
          {saveSettings.isPending
            ? translate("crm.common.saving")
            : translate("crm.common.save_changes")}
        </Button>
        <span className="settings-llm-footer-note">
          {trimmedApiKey
            ? translate("crm.common.unsaved_changes")
            : "API key được mã hoá, không hiển thị lại."}
        </span>
      </div>
    </SettingsSectionPanel>
  );
};
