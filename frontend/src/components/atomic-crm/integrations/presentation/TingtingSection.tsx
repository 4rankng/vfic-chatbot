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

/** The four Zalo credentials of the OA that serves the reset flow. */
type TingtingOaForm = {
  app_id: string;
  secret_key: string;
  access_token: string;
  refresh_token: string;
};

const EMPTY_OA_FORM: TingtingOaForm = {
  app_id: "",
  secret_key: "",
  access_token: "",
  refresh_token: "",
};

const describeOaLink = (settings: TingtingSettings | undefined): string => {
  if (!settings) return "Đang tải…";
  if (settings.oa_linked) {
    const name = settings.oa_name || settings.oa_label || "Zalo OA";
    return `Đã liên kết: ${name} (${settings.oa_id})`;
  }
  if (settings.oa_last_error) {
    return `Chưa liên kết được OA: ${settings.oa_last_error}`;
  }
  if (settings.oa_last_checked_at) {
    return "Chưa liên kết được OA.";
  }
  return "Chưa cấu hình Zalo OA cho TingTing.";
};

/**
 * The TingTing view: the deployment-wide API key for the password-reset API and
 * the Zalo OA that serves it.
 *
 * The OA is configured exactly like the recruiting OA card — the operator pastes
 * the four Zalo credentials and the backend checks them with Zalo (`getoa`),
 * which is what discovers the OA's own id. Nothing here asks for an account key
 * or an OA id; the flow is bound to whatever OA these credentials check out as.
 */
export const TingtingSection = () => {
  const notify = useNotify();
  const translate = useTranslate();
  const queryClient = useQueryClient();
  // Stored credentials never enter form state: a blank field means "keep stored".
  const [apiKey, setApiKey] = useState("");
  const [oaForm, setOaForm] = useState<TingtingOaForm>(EMPTY_OA_FORM);

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
      setOaForm(EMPTY_OA_FORM);
      queryClient.setQueryData(tingtingSettingsKey, data);
      if (data.oa_linked) {
        notify(`Đã liên kết Zalo OA: ${data.oa_name || data.oa_id}.`, {
          type: "success",
        });
      } else if (data.oa_last_error) {
        // The values are stored, but Zalo did not accept them — the flow stays off.
        notify(`Zalo OA chưa liên kết được: ${data.oa_last_error}`, {
          type: "error",
        });
      } else {
        notify("Đã lưu cấu hình TingTing.", { type: "success" });
      }
    },
    onError: () => {
      notify("Không thể lưu cấu hình TingTing.", { type: "error" });
    },
  });

  const checkOa = useMutation<TingtingSettings, Error, void>({
    mutationFn: () => zaloIntegrationGateway.checkTingtingOa(),
    onSuccess: (data) => {
      queryClient.setQueryData(tingtingSettingsKey, data);
      notify(
        data.oa_linked
          ? `Zalo OA hoạt động: ${data.oa_name || data.oa_id}.`
          : `Zalo OA chưa liên kết được: ${data.oa_last_error || "không rõ lý do"}`,
        { type: data.oa_linked ? "success" : "error" },
      );
    },
    onError: () => {
      notify("Không kiểm tra được Zalo OA.", { type: "error" });
    },
  });

  const setOaField = (key: keyof TingtingOaForm, value: string) =>
    setOaForm((current) => ({ ...current, [key]: value }));

  const trimmedApiKey = apiKey.trim();
  const oaPost: TingtingSettingsUpdate = {};
  const trimmedOa = {
    zalo_oa_app_id: oaForm.app_id.trim(),
    zalo_oa_secret_key: oaForm.secret_key.trim(),
    zalo_oa_access_token: oaForm.access_token.trim(),
    zalo_oa_refresh_token: oaForm.refresh_token.trim(),
  } as const;
  for (const [key, value] of Object.entries(trimmedOa)) {
    if (value) {
      oaPost[key as keyof TingtingSettingsUpdate] = value;
    }
  }

  const configured = settings?.configured ?? false;
  // Optional chaining on the credential objects too: a payload cached before
  // this card grew the OA fields must not crash the section.
  const oaConfigured = Boolean(
    settings?.oa_access_token?.configured ||
      settings?.oa_refresh_token?.configured ||
      settings?.oa_secret_key?.configured,
  );
  const dirty = Boolean(trimmedApiKey) || Object.keys(oaPost).length > 0;

  const submit = () => {
    saveSettings.mutate({
      ...(trimmedApiKey ? { api_key: trimmedApiKey } : {}),
      ...oaPost,
    });
  };

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
            configured={settings?.api_key?.configured ?? false}
            statusState={statusState}
            preview={settings?.api_key?.preview ?? null}
            value={apiKey}
            onChange={setApiKey}
            notify={notify}
            hint="Quy trình gửi OTP đã được tích hợp sẵn trong hệ thống. Để trống để giữ API key đã lưu."
          />
          <PlainField
            id="tingting_oa_app_id"
            label="Zalo App ID"
            placeholder="App ID của Zalo OA TingTing"
            value={oaForm.app_id || settings?.oa_app_id || ""}
            onChange={(value) => setOaField("app_id", value)}
            configured={Boolean(settings?.oa_app_id)}
            statusState={statusState}
            showMissingStatus={false}
            hint="Lấy trong Zalo OA Console của OA TingTing Software Solution (Cài đặt → API)."
          />
          <SecretField
            id="tingting_oa_secret_key"
            label="OA Secret Key"
            configured={settings?.oa_secret_key?.configured ?? false}
            statusState={statusState}
            preview={settings?.oa_secret_key?.preview ?? null}
            value={oaForm.secret_key}
            onChange={(value) => setOaField("secret_key", value)}
            notify={notify}
            hint="Dùng để tự động gia hạn Access Token (Zalo cấp cùng App ID)."
          />
          <SecretField
            id="tingting_oa_access_token"
            label="OA Access Token"
            configured={settings?.oa_access_token?.configured ?? false}
            statusState={statusState}
            preview={settings?.oa_access_token?.preview ?? null}
            value={oaForm.access_token}
            onChange={(value) => setOaField("access_token", value)}
            notify={notify}
            hint="Bắt buộc. Hệ thống kiểm tra bằng Zalo và tự nhận diện OA khi bạn lưu."
          />
          <SecretField
            id="tingting_oa_refresh_token"
            label="OA Refresh Token"
            configured={settings?.oa_refresh_token?.configured ?? false}
            statusState={statusState}
            preview={settings?.oa_refresh_token?.preview ?? null}
            value={oaForm.refresh_token}
            onChange={(value) => setOaField("refresh_token", value)}
            notify={notify}
            hint="Nên có: Access Token hết hạn sau ~25 giờ, thiếu Refresh Token thì OA sẽ ngừng gửi được tin."
          />
          <div className="settings-field">
            <div className="settings-field-label-row">
              <span className="settings-field-hint">
                {describeOaLink(settings)}
              </span>
            </div>
            {oaConfigured ? (
              <Button
                type="button"
                variant="outline"
                className="tt-btn-touch"
                onClick={() => checkOa.mutate()}
                disabled={checkOa.isPending}
              >
                {checkOa.isPending ? "Đang kiểm tra…" : "Kiểm tra lại OA"}
              </Button>
            ) : null}
          </div>
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
            : "Lưu & kiểm tra"}
        </Button>
        <span className="settings-llm-footer-note">
          {dirty
            ? translate("crm.common.unsaved_changes")
            : oaConfigured
              ? "Đặt lại mật khẩu chỉ chạy trên Zalo OA đã liên kết."
              : "Chưa liên kết Zalo OA nên chức năng đặt lại mật khẩu đang tắt."}
        </span>
      </div>
    </SettingsSectionPanel>
  );
};
