import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNotify, useTranslate } from "ra-core";

import { Button } from "@/components/ui/button";

import type { SettingsStatusState } from "../SettingsFieldStatus";
import { SettingsGroupStatus } from "../SettingsFieldStatus";
import {
  zaloIntegrationGateway,
  type TingtingSettings,
  type TingtingSettingsUpdate,
} from "../api";
import { PlainField, SecretField } from "./SecretField";
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
  // The OA pin is a plain value: seeded from the loaded settings, so an edit is
  // what makes the form dirty.
  const [resetOaId, setResetOaId] = useState("");
  const [resetOaIdTouched, setResetOaIdTouched] = useState(false);

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
      setResetOaId(data.reset_oa_id ?? "");
      setResetOaIdTouched(false);
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
  // The pin arrives with the loaded settings; an untouched field re-sends the
  // stored value, which is exactly what the PUT body means for it.
  const effectiveResetOaId = resetOaIdTouched
    ? resetOaId.trim()
    : (settings?.reset_oa_id ?? "").trim();
  const configured = settings?.configured ?? false;
  const storedResetOaId = (settings?.reset_oa_id ?? "").trim();

  const submit = () => {
    saveSettings.mutate({
      api_key: trimmedApiKey,
      reset_oa_id: effectiveResetOaId,
    });
  };
  const dirty =
    Boolean(trimmedApiKey) || effectiveResetOaId !== storedResetOaId;

  return (
    <SettingsSectionPanel id="settings-tingting">
      <div className="settings-grid settings-grid-models">
        <SettingsGroup
          className="settings-llm-card"
          title="TingTing · Đặt lại mật khẩu"
          description="Tra cứu nhân sự và gửi OTP đặt lại mật khẩu qua API TingTing trên Zalo OA TingTing Software Solution."
          icon={
            <img
              src="/brand/tingting-oa.png"
              alt="TingTing"
              className="size-6 rounded-[6px] object-contain"
            />
          }
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
          <PlainField
            id="tingting_reset_oa_id"
            label="Zalo OA chạy đặt lại mật khẩu"
            value={resetOaIdTouched ? resetOaId : (settings?.reset_oa_id ?? "")}
            onChange={(value) => {
              setResetOaId(value);
              setResetOaIdTouched(true);
            }}
            configured={Boolean(storedResetOaId)}
            statusState={statusState}
            showMissingStatus={false}
            hint="Account key của Zalo OA TingTing Software Solution (ví dụ default:zalo_oa). Chức năng đặt lại mật khẩu chỉ chạy trên kênh Zalo OA; để trống nghĩa là cho phép mọi OA đã kết nối. Kênh Bot tuyển dụng và Messenger không bao giờ chạy chức năng này."
          />
        </SettingsGroup>
      </div>

      <div className={`settings-llm-footer${dirty ? " is-dirty" : ""}`}>
        <Button
          type="button"
          className="settings-primary-action tt-btn-touch"
          onClick={submit}
          disabled={!dirty || saveSettings.isPending}
        >
          {saveSettings.isPending
            ? translate("crm.common.saving")
            : translate("crm.common.save_changes")}
        </Button>
        <span className="settings-llm-footer-note">
          {dirty
            ? translate("crm.common.unsaved_changes")
            : "API key được mã hoá, không hiển thị lại."}
        </span>
      </div>
    </SettingsSectionPanel>
  );
};
