import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNotify } from "ra-core";
import { Clock, FileText, Mail, PhoneCall } from "lucide-react";

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
import { integrationSettingsKeys } from "./useSettingsBundle";

/**
 * The badge-counted fields: the three CloudFone spec-1.1 credentials
 * (ServiceName, AuthUser, AuthKey) plus the recipient list.
 */
const CLOUDFONE_FIELD_COUNT = 4;

/** One query key for the endpoint, so a save can write back its own response. */
const cloudfoneSettingsKey = integrationSettingsKeys.cloudfone;

/**
 * The Cloudfone (CloudFone tổng đài) voice-transcript insights view: the three
 * CloudFone spec-1.1 credentials, the recipient list, and the daily-send
 * toggle. Blank credentials mean "keep the stored ones"; the whole feature
 * stays off until ServiceName AND AuthUser AND AuthKey AND a non-empty
 * recipient list are saved with cron enabled.
 */
export const CloudfoneSection = ({
  onOpenTranscripts,
}: {
  onOpenTranscripts?: () => void;
}) => {
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
          {/* Quick Metrics Bar (Data-Dense Overview) */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 p-2 rounded-lg border border-border/60 bg-muted/30">
            <div className="flex items-center gap-2.5 px-2 py-1">
              <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                <PhoneCall className="size-3.5" />
              </div>
              <div className="min-w-0 flex-1">
                <span className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                  CloudFone API 1.1
                </span>
                <span className="block truncate text-xs font-semibold text-foreground">
                  {configuredFields === CLOUDFONE_FIELD_COUNT
                    ? "Đã cấu hình đủ"
                    : `${configuredFields}/${CLOUDFONE_FIELD_COUNT} thông số`}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2.5 px-2 py-1 border-t sm:border-t-0 sm:border-l border-border/40">
              <div
                className={`flex size-7 shrink-0 items-center justify-center rounded-md ${
                  enabled
                    ? "bg-emerald-500/10 text-emerald-600"
                    : "bg-muted text-muted-foreground"
                }`}
              >
                <Clock className="size-3.5" />
              </div>
              <div className="min-w-0 flex-1">
                <span className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                  Lịch gửi tự động
                </span>
                <span className="block truncate text-xs font-semibold text-foreground">
                  {enabled ? "08:00 hàng ngày (GMT+7)" : "Đang tạm tắt"}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2.5 px-2 py-1 border-t sm:border-t-0 sm:border-l border-border/40">
              <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-blue-500/10 text-blue-600">
                <Mail className="size-3.5" />
              </div>
              <div className="min-w-0 flex-1">
                <span className="block text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                  Người nhận báo cáo
                </span>
                <span className="block truncate text-xs font-semibold text-foreground">
                  {parsedRecipients.length > 0
                    ? `${parsedRecipients.length} email đăng ký`
                    : "Chưa có người nhận"}
                </span>
              </div>
            </div>
          </div>

          {/* 3-Column API Credentials Row */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <PlainField
              id="cloudfone_service_name"
              label="CloudFone ServiceName"
              configured={storedServiceName.length > 0}
              statusState={statusState}
              showMissingStatus={false}
              value={serviceNameValue}
              onChange={setServiceNameDraft}
            />
            <PlainField
              id="cloudfone_auth_user"
              label="CloudFone AuthUser"
              configured={storedAuthUser.length > 0}
              statusState={statusState}
              showMissingStatus={false}
              value={authUserValue}
              onChange={setAuthUserDraft}
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
            />
          </div>
          <p className="text-body-xs text-text-substandard -mt-2">
            Bộ ba ServiceName + AuthUser + AuthKey dùng để kết nối API 1.1 tổng
            đài CloudFone. Để trống để giữ nguyên giá trị đã lưu.
          </p>

          {/* 2-Column Responsive Workspace: Recipients (Left 7 cols) & Schedule/Cron (Right 5 cols) */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
            {/* Cột 1: Danh sách email */}
            <div className="lg:col-span-7 flex flex-col gap-1.5 p-3 rounded-lg border border-border/60 bg-muted/20">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Mail className="size-3.5 text-muted-foreground" />
                  <label
                    htmlFor="cloudfone_recipients"
                    className="text-body-sm font-medium text-foreground"
                  >
                    Danh sách email người nhận
                  </label>
                </div>
                <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                  {parsedRecipients.length} email
                </span>
              </div>
              <Textarea
                id="cloudfone_recipients"
                value={recipientsValue}
                onChange={(event) => setRecipientsDraft(event.target.value)}
                placeholder={"quanly@congty.vn\nkd@congty.vn"}
                rows={3}
                className="font-mono text-xs leading-relaxed resize-none bg-background"
              />
              <p className="text-body-xs text-text-substandard">
                Phân tách bằng dấu phẩy hoặc xuống dòng. Danh sách trống = tắt
                email phân tích cuộc gọi.
              </p>
            </div>

            {/* Cột 2: Lịch gửi & Cron Toggle */}
            <div className="lg:col-span-5 flex flex-col justify-between gap-2.5 p-3 rounded-lg border border-border/60 bg-muted/20">
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <Clock className="size-3.5 text-muted-foreground" />
                    <span className="text-body-sm font-medium text-foreground">
                      Lịch gửi tự động (Cron)
                    </span>
                  </div>
                  <span
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                      enabled
                        ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
                        : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                    }`}
                  >
                    <span
                      className={`size-1.5 rounded-full ${
                        enabled ? "bg-emerald-500 animate-pulse" : "bg-zinc-400"
                      }`}
                    />
                    {enabled ? "Đang bật" : "Đang tắt"}
                  </span>
                </div>
                <p className="text-body-xs text-text-substandard leading-relaxed">
                  Báo cáo kèm file Word (.docx) và biểu đồ được gửi định kỳ lúc{" "}
                  <strong className="text-foreground">08:00 sáng</strong> hàng
                  ngày (giờ Việt Nam).
                </p>
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-border/40">
                <span className="text-body-xs text-foreground font-medium">
                  Bật/tắt gửi email phân tích hàng ngày
                </span>
                <div
                  className="inline-flex rounded-lg border border-border/60 bg-muted/60 p-0.5"
                  role="group"
                  aria-label="Bật tắt cron Cloudfone"
                >
                  <Button
                    type="button"
                    size="sm"
                    color={enabled ? "primary" : "secondary"}
                    className="uu-scope text-xs px-2.5 py-1 font-medium"
                    aria-pressed={enabled}
                    onClick={() => setEnabledDraft(true)}
                  >
                    Bật cron
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    color={enabled ? "secondary" : "primary"}
                    className="uu-scope text-xs px-2.5 py-1 font-medium"
                    aria-pressed={!enabled}
                    onClick={() => setEnabledDraft(false)}
                  >
                    Tắt cron
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Action & Status Strip */}
          <div className="settings-tingting-link flex flex-wrap items-center justify-between gap-3 p-2.5 rounded-lg border border-border/60 bg-muted/20">
            <span
              className="settings-tingting-link-copy text-body-xs flex items-center gap-1.5"
              role="status"
            >
              <span
                className={`size-2 shrink-0 rounded-full ${
                  enabled ? "bg-emerald-500" : "bg-amber-500"
                }`}
              />
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
            <div className="flex items-center gap-2">
              <Button
                type="button"
                color="secondary"
                size="sm"
                className="uu-scope settings-test-button tt-btn-touch text-xs font-medium"
                onClick={() => testConnection.mutate(probeDraft())}
                isDisabled={testConnection.isPending}
                aria-busy={testConnection.isPending}
              >
                {testConnection.isPending
                  ? "Đang kiểm tra…"
                  : "Kiểm tra kết nối"}
              </Button>
            </div>
          </div>
        </SettingsGroup>

        <div className={`settings-llm-footer${dirty ? " is-dirty" : ""}`}>
          {onOpenTranscripts ? (
            <Button
              type="button"
              color="secondary"
              className="tt-btn-touch text-xs flex items-center gap-1.5"
              aria-label="Xem bản ghi cuộc gọi"
              onClick={onOpenTranscripts}
            >
              <FileText className="size-4" />
              Xem
            </Button>
          ) : null}
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
              : "Hệ thống lấy bản ghi cuộc gọi từ CloudFone, tự động phân tích và gửi báo cáo tổng hợp."}
          </span>
        </div>
      </fieldset>
    </SettingsSectionPanel>
  );
};
