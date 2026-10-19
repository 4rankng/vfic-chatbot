import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNotify } from "ra-core";
import { PhoneCall } from "lucide-react";

import { Button } from "@/components/base/buttons/button";
import { Textarea } from "@/components/ui/textarea";

import {
  zaloIntegrationGateway,
  type OdsSettings,
  type OdsSettingsUpdate,
  type OdsTestResult,
} from "./api";
import type { SettingsStatusState } from "./SettingsFieldStatus";
import { SettingsGroupStatus } from "./SettingsFieldStatus";
import { SecretField } from "./SecretField";
import { SettingsGroup, SettingsSectionPanel } from "./SettingsGroup";

/** The CloudFone API key and the recipient list — the two badge-counted fields. */
const ODS_FIELD_COUNT = 2;

/** One query key for the endpoint, so a save can write back its own response. */
const odsSettingsKey = ["ods-settings"] as const;

/**
 * The ODS (CloudFone tổng đài) voice-transcript insights view: the CloudFone
 * API key, the recipient list, and the daily-send toggle. A blank key means
 * "keep the stored one"; the whole feature stays off until the key AND a
 * non-empty recipient list are saved with cron enabled.
 */
export const OdsSection = () => {
  const notify = useNotify();
  const queryClient = useQueryClient();
  // Untouched-draft sentinels: null shows (and keeps tracking) the server value.
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [recipientsDraft, setRecipientsDraft] = useState<string | null>(null);
  const [enabledDraft, setEnabledDraft] = useState<boolean | null>(null);

  const settingsQuery = useQuery<OdsSettings>({
    queryKey: odsSettingsKey,
    queryFn: () => zaloIntegrationGateway.loadOdsSettings(),
    staleTime: 30_000,
  });
  const { data: settings, isPending, isError } = settingsQuery;

  const statusState: SettingsStatusState = isPending
    ? "loading"
    : isError
      ? "error"
      : "ready";

  const saveSettings = useMutation<OdsSettings, Error, OdsSettingsUpdate>({
    mutationFn: (body) => zaloIntegrationGateway.saveOdsSettings(body),
    onSuccess: (data) => {
      setApiKeyDraft("");
      setRecipientsDraft(null);
      setEnabledDraft(null);
      queryClient.setQueryData(odsSettingsKey, data);
      notify(
        data.enabled
          ? "Đã lưu cấu hình ODS."
          : "Đã lưu. Tích hợp ODS đang tắt.",
        { type: data.enabled ? "success" : "info" },
      );
    },
    onError: () => {
      notify("Không thể lưu cấu hình ODS.", { type: "error" });
    },
  });

  const testConnection = useMutation<OdsTestResult, Error, string | undefined>({
    // The probe validates the typed key BEFORE it is saved; without a draft
    // the stored key is probed instead.
    mutationFn: (apiKey) => zaloIntegrationGateway.testOdsConnection(apiKey),
    onSuccess: (result) => {
      if (result.ok) {
        notify(
          `Kết nối CloudFone thành công${result.latency_ms != null ? ` (${result.latency_ms} ms)` : ""}.`,
          { type: "success" },
        );
      } else if (!result.configured) {
        notify(`Chưa cấu hình đủ: ${result.missing.join(", ")}.`, {
          type: "error",
        });
      } else {
        notify(`Kết nối thất bại: ${result.error ?? "không rõ lý do"}`, {
          type: "error",
        });
      }
    },
    onError: () => {
      notify("Không kiểm tra được kết nối CloudFone.", { type: "error" });
    },
  });

  const storedRecipients = settings?.recipients ?? [];
  const recipientsValue = recipientsDraft ?? storedRecipients.join(",\n");
  const enabled = enabledDraft ?? settings?.enabled ?? false;
  const trimmedApiKey = apiKeyDraft.trim();

  const parsedRecipients = recipientsValue
    .split(/[,\n]/)
    .map((email) => email.trim())
    .filter(Boolean);
  const recipientsChanged =
    recipientsDraft !== null &&
    recipientsValue.trim() !== storedRecipients.join(", ");
  const dirty =
    Boolean(trimmedApiKey) || recipientsChanged || enabledDraft !== null;

  const configuredFields = [
    settings?.api_key?.configured,
    storedRecipients.length > 0,
  ].filter(Boolean).length;

  const submit = () => {
    if (!settings || isError || saveSettings.isPending || !dirty) return;
    saveSettings.mutate({
      ...(trimmedApiKey ? { api_key: trimmedApiKey } : {}),
      recipients: parsedRecipients,
      ...(enabledDraft !== null ? { enabled: enabledDraft } : {}),
    });
  };

  return (
    <SettingsSectionPanel id="settings-ods">
      {isError ? (
        <div role="alert" className="mb-3 text-body-sm">
          <p>Chưa tải được cấu hình ODS.</p>
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
        <legend className="sr-only">Cấu hình ODS</legend>
        <SettingsGroup
          className="settings-tingting-card"
          title="CloudFone API & người nhận"
          icon={<PhoneCall className="size-5" aria-hidden="true" />}
          meta={
            <SettingsGroupStatus
              configured={configuredFields}
              total={ODS_FIELD_COUNT}
              state={statusState}
            />
          }
          defaultOpen
        >
          <SecretField
            id="ods_api_key"
            label="CloudFone API key"
            placeholder="Nhập CloudFone API key"
            configured={settings?.api_key?.configured ?? false}
            statusState={statusState}
            preview={settings?.api_key?.preview ?? null}
            value={apiKeyDraft}
            onChange={setApiKeyDraft}
            notify={notify}
            hint="Để trống để giữ key đã lưu. Key dùng để lấy bản ghi (transcript) cuộc gọi tổng đài mỗi ngày."
          />

          <div className="settings-tingting-subhead">
            <h3>Người nhận</h3>
            <p>Danh sách trống = tắt email phân tích cuộc gọi.</p>
          </div>
          <label
            htmlFor="ods_recipients"
            className="text-body-sm text-foreground"
          >
            Danh sách email người nhận
          </label>
          <Textarea
            id="ods_recipients"
            value={recipientsValue}
            onChange={(event) => setRecipientsDraft(event.target.value)}
            placeholder={"quanly@congty.vn\nkd@congty.vn"}
            rows={3}
            className="min-h-10"
          />
          <p className="text-body-xs text-text-substandard">
            Phân tách bằng dấu phẩy hoặc xuống dòng. Email phân tích được gửi
            lúc 08:00 sáng (giờ Việt Nam) với các cuộc gọi của ngày hôm trước.
          </p>

          <div className="settings-tingting-subhead">
            <h3>Cron</h3>
            <p>Bật/tắt gửi email phân tích hàng ngày.</p>
          </div>
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label="Bật tắt cron ODS"
          >
            <Button
              type="button"
              size="sm"
              color={enabled ? "primary" : "secondary"}
              className="uu-scope tt-btn-touch"
              aria-pressed={enabled}
              onClick={() => setEnabledDraft(true)}
            >
              Bật cron
            </Button>
            <Button
              type="button"
              size="sm"
              color={enabled ? "secondary" : "primary"}
              className="uu-scope tt-btn-touch"
              aria-pressed={!enabled}
              onClick={() => setEnabledDraft(false)}
            >
              Tắt cron
            </Button>
          </div>

          <div className="settings-tingting-link">
            <span className="settings-tingting-link-copy" role="status">
              {enabled
                ? "ODS đang bật. Email phân tích sẽ gửi hàng ngày lúc 08:00 (giờ VN)."
                : enabledDraft === false
                  ? "ODS sẽ tắt sau khi bấm Lưu cấu hình."
                  : storedRecipients.length === 0 ||
                      !settings?.api_key?.configured
                    ? "ODS đang tắt — cần CloudFone API key và ít nhất một người nhận."
                    : "ODS đang tắt — bấm Bật cron rồi Lưu cấu hình để bật."}
            </span>
            <Button
              type="button"
              color="secondary"
              className="uu-scope settings-test-button tt-btn-touch"
              onClick={() => testConnection.mutate(trimmedApiKey || undefined)}
              isDisabled={testConnection.isPending}
              aria-busy={testConnection.isPending}
            >
              {testConnection.isPending ? "Đang kiểm tra…" : "Kiểm tra kết nối"}
            </Button>
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
            {saveSettings.isPending ? "Đang lưu…" : "Lưu cấu hình"}
          </Button>
          <span className="settings-llm-footer-note">
            {dirty
              ? "Có thay đổi chưa lưu."
              : "Hệ thống lấy phân tích cuộc gọi (voice transcript) từ CloudFone, tóm tắt bằng AI và gửi email cho người nhận."}
          </span>
        </div>
      </fieldset>
    </SettingsSectionPanel>
  );
};
