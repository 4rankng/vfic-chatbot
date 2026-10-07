import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNotify, useTranslate } from "ra-core";

import { Button } from "@/components/base/buttons/button";

import type { SettingsStatusState } from "./SettingsFieldStatus";
import { SettingsGroupStatus } from "./SettingsFieldStatus";
import {
  zaloIntegrationGateway,
  type TingtingSettings,
  type TingtingSettingsUpdate,
} from "./api";
import { formatVietnamDateTime } from "../vietnamTime";
import { PlainField, SecretField } from "./SecretField";
import { SettingsGroup, SettingsSectionPanel } from "./SettingsGroup";

/** The admin-editable inputs this panel owns: the API key and the hotline. */
const TINGTING_FIELD_COUNT = 2;

/** One query key for the endpoint, so a save can write back its own response. */
const tingtingSettingsKey = ["tingting-settings"] as const;

const describeToken = (settings: TingtingSettings | undefined): string => {
  if (!settings) return "Đang tải…";
  if (settings.oa_token_updated_at) {
    return `Token Zalo OA cập nhật lúc ${formatVietnamDateTime(settings.oa_token_updated_at)}.`;
  }
  return "Chưa nhận được token Zalo OA từ Payroll — token sẽ tự có khi Payroll đẩy hoặc khi hệ thống kéo.";
};

/**
 * The TingTing view: the deployment-wide API key, the escalation hotline, and
 * the message-processing switch for the Zalo OA that serves the password
 * resets.
 *
 * The OA's Zalo credentials are not admin input: Payroll solely owns and
 * rotates the token pair and pushes it to the backend, so the card renders the
 * token's last update and the fixed ownership note instead of four credential
 * fields. The OA id/name still come from the verified link metadata.
 */
export const TingtingSection = () => {
  const notify = useNotify();
  const translate = useTranslate();
  const queryClient = useQueryClient();
  // Stored credentials never enter form state: a blank field means "keep stored".
  const [apiKey, setApiKey] = useState("");
  // The hotline field pre-fills with the stored value (it is not a secret), so
  // its draft holds the EDIT only; saving keeps the stored number when the
  // field is untouched or cleared — the backend never loses the seed by accident.
  const [hotlineDraft, setHotlineDraft] = useState("");

  const settingsQuery = useQuery<TingtingSettings>({
    queryKey: tingtingSettingsKey,
    queryFn: () => zaloIntegrationGateway.loadTingtingSettings(),
    staleTime: 30_000,
  });
  const { data: settings, isPending, isError } = settingsQuery;

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
      setHotlineDraft("");
      queryClient.setQueryData(tingtingSettingsKey, data);
      notify("Đã lưu cấu hình TingTing.", { type: "success" });
    },
    onError: () => {
      notify("Không thể lưu cấu hình TingTing.", { type: "error" });
    },
  });

  const trimmedApiKey = apiKey.trim();
  const storedHotline = settings?.hotline ?? "";
  const trimmedHotline = hotlineDraft.trim();
  const hotlineChanged =
    Boolean(trimmedHotline) && trimmedHotline !== storedHotline;

  // The switch falls back to on while the settings are loading, so the toggle
  // never renders a disabled-looking half state before the truth arrives.
  const oaEnabled = oaEnabledDraft ?? settings?.tingting_oa_enabled ?? true;
  const dirty =
    Boolean(trimmedApiKey) || hotlineChanged || oaEnabledDraft !== null;

  // The badge counts the admin-editable inputs, so the section reports how
  // much of what the ADMIN owns is configured — the OA token is Payroll's.
  const configuredFields = [
    settings?.api_key?.configured,
    Boolean(storedHotline),
  ].filter(Boolean).length;

  const submit = () => {
    if (!settings || isError || saveSettings.isPending || !dirty) return;
    saveSettings.mutate({
      ...(trimmedApiKey ? { api_key: trimmedApiKey } : {}),
      ...(hotlineChanged ? { hotline: trimmedHotline } : {}),
      ...(oaEnabledDraft !== null
        ? { tingting_oa_enabled: oaEnabledDraft }
        : {}),
    });
  };

  return (
    <SettingsSectionPanel id="settings-tingting">
      {isError ? (
        <div role="alert" className="mb-3 text-body-sm">
          <p>Chưa tải được cấu hình TingTing.</p>
          <Button
            type="button"
            color="secondary"
            size="sm"
            className="uu-scope mt-2"
            isDisabled={settingsQuery.isFetching}
            onClick={() => void settingsQuery.refetch()}
          >
            {settingsQuery.isFetching ? "Đang tải…" : "Thử lại cấu hình"}
          </Button>
        </div>
      ) : null}
      <fieldset
        className="contents"
        disabled={!settings || isError || saveSettings.isPending}
        aria-busy={saveSettings.isPending}
      >
        <legend className="sr-only">Thông tin kết nối TingTing</legend>
        {/* One integration, so one full-width card: the page header already
          carries the title and the purpose. The card names the integration,
          reports how much of it is configured, and lays the fields out in
          pairs instead of a single tall column. */}
        <SettingsGroup
          className="settings-tingting-card"
          title="TingTing"
          icon={
            <img
              src="/brand/tingting-oa.png"
              alt=""
              className="size-5 rounded-[6px] object-contain"
            />
          }
          meta={
            <SettingsGroupStatus
              configured={configuredFields}
              total={TINGTING_FIELD_COUNT}
              state={statusState}
            />
          }
          defaultOpen
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
            hint="Quy trình gửi OTP đã tích hợp sẵn. Để trống để giữ API key đã lưu."
          />

          <PlainField
            id="tingting_hotline"
            label="Hotline hỗ trợ"
            value={hotlineDraft || storedHotline}
            onChange={setHotlineDraft}
            configured={Boolean(storedHotline)}
            statusState={statusState}
            showMissingStatus={false}
            hint="Số bot đưa khi không hỗ trợ được qua tin nhắn. Đã đặt sẵn — sửa khi cần đổi số."
          />

          <div className="settings-tingting-subhead">
            <h3>Zalo OA</h3>
            <p>
              {settings?.oa_token_managed_note ||
                "Payroll quản lý và tự gia hạn token Zalo OA."}
            </p>
          </div>

          <div className="settings-tingting-link">
            <span className="settings-tingting-link-copy" role="status">
              {describeToken(settings)}
            </span>
          </div>
        </SettingsGroup>

        <div className={`settings-llm-footer${dirty ? " is-dirty" : ""}`}>
          <Button
            type="button"
            color="primary"
            className="settings-primary-action tt-btn-touch"
            onClick={submit}
            isDisabled={!dirty || saveSettings.isPending}
          >
            {saveSettings.isPending
              ? translate("crm.common.saving")
              : translate("crm.common.save_and_test")}
          </Button>
          <span className="settings-llm-footer-note">
            {dirty
              ? translate("crm.common.unsaved_changes")
              : settings?.oa_linked
                ? "Đặt lại mật khẩu chỉ chạy trên Zalo OA đã liên kết."
                : "Chưa liên kết Zalo OA nên chức năng đặt lại mật khẩu đang tắt."}
          </span>
        </div>
      </fieldset>
    </SettingsSectionPanel>
  );
};
