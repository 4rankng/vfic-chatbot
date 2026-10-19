import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNotify } from "ra-core";
import { PhoneCall } from "lucide-react";

import { Button } from "@/components/base/buttons/button";
import { Textarea } from "@/components/ui/textarea";

import {
  zaloIntegrationGateway,
  type CloudfoneSettings,
  type CloudfoneSettingsUpdate,
  type CloudfoneTestResult,
} from "./api";
import type { SettingsStatusState } from "./SettingsFieldStatus";
import { SettingsGroupStatus } from "./SettingsFieldStatus";
import { PlainField, SecretField } from "./SecretField";
import { SettingsGroup, SettingsSectionPanel } from "./SettingsGroup";

/**
 * The badge-counted fields: the three CloudFone spec-1.1 credentials
 * (ServiceName, AuthUser, AuthKey) plus the recipient list.
 */
const CLOUDFONE_FIELD_COUNT = 4;

/** One query key for the endpoint, so a save can write back its own response. */
const cloudfoneSettingsKey = ["cloudfone-settings"] as const;

/**
 * The Cloudfone (CloudFone tổng đài) voice-transcript insights view: the three
 * CloudFone spec-1.1 credentials, the recipient list, and the daily-send
 * toggle. Blank credentials mean "keep the stored ones"; the whole feature
 * stays off until ServiceName AND AuthUser AND AuthKey AND a non-empty
 * recipient list are saved with cron enabled.
 */
export const CloudfoneSection = () => {
  const notify = useNotify();
  const queryClient = useQueryClient();
  // Untouched-draft sentinels: null shows (and keeps tracking) the server value.
  const [serviceNameDraft, setServiceNameDraft] = useState<string | null>(null);
  const [authUserDraft, setAuthUserDraft] = useState<string | null>(null);
  const [authKeyDraft, setAuthKeyDraft] = useState("");
  const [recipientsDraft, setRecipientsDraft] = useState<string | null>(null);
  const [enabledDraft, setEnabledDraft] = useState<boolean | null>(null);

  const settingsQuery = useQuery<CloudfoneSettings>({
    queryKey: cloudfoneSettingsKey,
    queryFn: () => zaloIntegrationGateway.loadCloudfoneSettings(),
    staleTime: 30_000,
  });
  const { data: settings, isPending, isError } = settingsQuery;

  const statusState: SettingsStatusState = isPending
    ? "loading"
    : isError
      ? "error"
      : "ready";

  const saveSettings = useMutation<
    CloudfoneSettings,
    Error,
    CloudfoneSettingsUpdate
  >({
    mutationFn: (body) => zaloIntegrationGateway.saveCloudfoneSettings(body),
    onSuccess: (data) => {
      setServiceNameDraft(null);
      setAuthUserDraft(null);
      setAuthKeyDraft("");
      setRecipientsDraft(null);
      setEnabledDraft(null);
      queryClient.setQueryData(cloudfoneSettingsKey, data);
      notify(
        data.enabled
          ? "Đã lưu cấu hình Cloudfone."
          : "Đã lưu. Tích hợp Cloudfone đang tắt.",
        { type: data.enabled ? "success" : "info" },
      );
    },
    onError: () => {
      notify("Không thể lưu cấu hình Cloudfone.", { type: "error" });
    },
  });

  const testConnection = useMutation<
    CloudfoneTestResult,
    Error,
    CloudfoneSettingsUpdate | undefined
  >({
    // The probe validates the typed credentials BEFORE they are saved; without
    // a draft the stored credentials are probed instead.
    mutationFn: (body) => zaloIntegrationGateway.testCloudfoneConnection(body),
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

  const storedServiceName = settings?.service_name ?? "";
  const storedAuthUser = settings?.auth_user ?? "";
  const storedRecipients = settings?.recipients ?? [];
  const serviceNameValue = serviceNameDraft ?? storedServiceName;
  const authUserValue = authUserDraft ?? storedAuthUser;
  const recipientsValue = recipientsDraft ?? storedRecipients.join(",\n");
  const enabled = enabledDraft ?? settings?.enabled ?? false;
  const trimmedAuthKey = authKeyDraft.trim();

  const parsedRecipients = recipientsValue
    .split(/[,\n]/)
    .map((email) => email.trim())
    .filter(Boolean);
  const serviceNameChanged =
    serviceNameDraft !== null && serviceNameValue.trim() !== storedServiceName;
  const authUserChanged =
    authUserDraft !== null && authUserValue.trim() !== storedAuthUser;
  const recipientsChanged =
    recipientsDraft !== null &&
    recipientsValue.trim() !== storedRecipients.join(", ");
  const dirty =
    serviceNameChanged ||
    authUserChanged ||
    Boolean(trimmedAuthKey) ||
    recipientsChanged ||
    enabledDraft !== null;

  const configuredFields = [
    storedServiceName.length > 0,
    storedAuthUser.length > 0,
    settings?.auth_key?.configured,
    storedRecipients.length > 0,
  ].filter(Boolean).length;

  /** Typed credentials only — omitted fields probe the stored values. */
  const probeDraft = (): CloudfoneSettingsUpdate | undefined => {
    const body: CloudfoneSettingsUpdate = {};
    if (serviceNameDraft !== null && serviceNameDraft.trim()) {
      body.service_name = serviceNameDraft.trim();
    }
    if (authUserDraft !== null && authUserDraft.trim()) {
      body.auth_user = authUserDraft.trim();
    }
    if (trimmedAuthKey) body.auth_key = trimmedAuthKey;
    return Object.keys(body).length > 0 ? body : undefined;
  };

  const submit = () => {
    if (!settings || isError || saveSettings.isPending || !dirty) return;
    saveSettings.mutate({
      ...(serviceNameChanged ? { service_name: serviceNameValue.trim() } : {}),
      ...(authUserChanged ? { auth_user: authUserValue.trim() } : {}),
      ...(trimmedAuthKey ? { auth_key: trimmedAuthKey } : {}),
      recipients: parsedRecipients,
      ...(enabledDraft !== null ? { enabled: enabledDraft } : {}),
    });
  };

  return (
    <SettingsSectionPanel id="settings-cloudfone">
      {isError ? (
        <div role="alert" className="mb-3 text-body-sm">
          <p>Chưa tải được cấu hình Cloudfone.</p>
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
        <legend className="sr-only">Cấu hình Cloudfone</legend>
        <SettingsGroup
          className="settings-tingting-card"
          title="CloudFone API & người nhận"
          icon={<PhoneCall className="size-5" aria-hidden="true" />}
          meta={
            <SettingsGroupStatus
              configured={configuredFields}
              total={CLOUDFONE_FIELD_COUNT}
              state={statusState}
            />
          }
          defaultOpen
        >
          <PlainField
            id="cloudfone_service_name"
            label="CloudFone ServiceName"
            configured={storedServiceName.length > 0}
            statusState={statusState}
            showMissingStatus={false}
            value={serviceNameValue}
            onChange={setServiceNameDraft}
            hint="Tên dịch vụ trong body request CloudFone API 1.1. Để trống để giữ giá trị đã lưu."
          />
          <PlainField
            id="cloudfone_auth_user"
            label="CloudFone AuthUser"
            configured={storedAuthUser.length > 0}
            statusState={statusState}
            showMissingStatus={false}
            value={authUserValue}
            onChange={setAuthUserDraft}
            hint="Tài khoản xác thực CloudFone API 1.1. Để trống để giữ giá trị đã lưu."
          />
          <SecretField
            id="cloudfone_auth_key"
            label="CloudFone AuthKey"
            placeholder="Nhập CloudFone AuthKey"
            configured={settings?.auth_key?.configured ?? false}
            statusState={statusState}
            preview={settings?.auth_key?.preview ?? null}
            value={authKeyDraft}
            onChange={setAuthKeyDraft}
            notify={notify}
            hint="Để trống để giữ key đã lưu. Bộ ba ServiceName + AuthUser + AuthKey dùng để lấy bản ghi cuộc gọi tổng đài mỗi ngày."
          />

          <div className="settings-tingting-subhead">
            <h3>Người nhận</h3>
            <p>Danh sách trống = tắt email phân tích cuộc gọi.</p>
          </div>
          <label
            htmlFor="cloudfone_recipients"
            className="text-body-sm text-foreground"
          >
            Danh sách email người nhận
          </label>
          <Textarea
            id="cloudfone_recipients"
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
            aria-label="Bật tắt cron Cloudfone"
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
                ? "Cloudfone đang bật. Email phân tích sẽ gửi hàng ngày lúc 08:00 (giờ VN)."
                : enabledDraft === false
                  ? "Cloudfone sẽ tắt sau khi bấm Lưu cấu hình."
                  : storedRecipients.length === 0 ||
                      !storedServiceName ||
                      !storedAuthUser ||
                      !settings?.auth_key?.configured
                    ? "Cloudfone đang tắt — cần đủ ServiceName, AuthUser, AuthKey và ít nhất một người nhận."
                    : "Cloudfone đang tắt — bấm Bật cron rồi Lưu cấu hình để bật."}
            </span>
            <Button
              type="button"
              color="secondary"
              className="uu-scope settings-test-button tt-btn-touch"
              onClick={() => testConnection.mutate(probeDraft())}
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
