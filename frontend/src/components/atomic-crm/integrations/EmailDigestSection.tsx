import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNotify } from "ra-core";
import { Mail } from "lucide-react";

import { formatVietnamDateTime } from "../vietnamTime";

import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import {
  zaloIntegrationGateway,
  type EmailDigestFrequency,
  type EmailDigestSettings,
  type EmailDigestSettingsUpdate,
} from "./api";
import type { SettingsStatusState } from "./SettingsFieldStatus";
import { SettingsGroupStatus } from "./SettingsFieldStatus";
import { SecretField } from "./SecretField";
import { SettingsGroup, SettingsSectionPanel } from "./SettingsGroup";

/** The Resend key and the recipient list — the two fields the badge counts. */
const EMAIL_DIGEST_FIELD_COUNT = 2;

/** One query key for the endpoint, so a save can write back its own response. */
const emailDigestSettingsKey = ["email-digest-settings"] as const;

/** Half-hour send-time options (ICT), matching what the worker accepts. */
const SEND_TIMES: string[] = Array.from({ length: 48 }, (_, index) => {
  const hour = Math.floor(index / 2);
  const minute = index % 2 === 0 ? "00" : "30";
  return `${String(hour).padStart(2, "0")}:${minute}`;
});

const FREQUENCY_LABELS: Record<EmailDigestFrequency, string> = {
  daily: "Hàng ngày",
  weekly: "Hàng tuần",
};

const describeSchedule = (
  frequency: EmailDigestFrequency,
  sendTime: string,
): string => {
  const [hour, minute] = sendTime.split(":");
  const time = `${hour}h${minute}`;
  return frequency === "daily"
    ? `Gửi lúc ${time} mỗi ngày (giờ Việt Nam).`
    : `Gửi lúc ${time} thứ Hai hàng tuần (giờ Việt Nam).`;
};

/**
 * The candidate email digest view: the Resend key, the recipient list, and the
 * send schedule. A blank key means "keep the stored one" (the deployment env
 * `RESEND_API_KEY` serves as fallback), and an empty recipient list turns the
 * whole feature off — there is nowhere to send to.
 */
export const EmailDigestSection = () => {
  const notify = useNotify();
  const queryClient = useQueryClient();
  // Untouched-draft sentinels: null shows (and keeps tracking) the server value.
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [recipientsDraft, setRecipientsDraft] = useState<string | null>(null);
  const [frequencyDraft, setFrequencyDraft] =
    useState<EmailDigestFrequency | null>(null);
  const [sendTimeDraft, setSendTimeDraft] = useState<string | null>(null);
  const [enabledDraft, setEnabledDraft] = useState<boolean | null>(null);
  const [previewEmailDraft, setPreviewEmailDraft] = useState("");

  const settingsQuery = useQuery<EmailDigestSettings>({
    queryKey: emailDigestSettingsKey,
    queryFn: () => zaloIntegrationGateway.loadEmailDigestSettings(),
    staleTime: 30_000,
  });
  const { data: settings, isPending, isError } = settingsQuery;

  const statusState: SettingsStatusState = isPending
    ? "loading"
    : isError
      ? "error"
      : "ready";

  const saveSettings = useMutation<
    EmailDigestSettings,
    Error,
    EmailDigestSettingsUpdate
  >({
    mutationFn: (body) => zaloIntegrationGateway.saveEmailDigestSettings(body),
    onSuccess: (data) => {
      setApiKeyDraft("");
      setRecipientsDraft(null);
      setFrequencyDraft(null);
      setSendTimeDraft(null);
      setEnabledDraft(null);
      queryClient.setQueryData(emailDigestSettingsKey, data);
      notify(
        data.enabled
          ? "Đã lưu cấu hình email ứng viên mới."
          : "Đã lưu. Email đang tắt.",
        { type: data.enabled ? "success" : "info" },
      );
    },
    onError: () => {
      notify("Không thể lưu cấu hình email.", { type: "error" });
    },
  });

  const testSend = useMutation({
    // The preview delivers the REAL pending digest (same subject, body and
    // workbook as the scheduled send) to one typed address — never to the
    // configured recipient list.
    mutationFn: (toEmail: string) =>
      zaloIntegrationGateway.testEmailDigest(toEmail),
    onSuccess: (result) => {
      if (result.ok) {
        notify(
          `Đã gửi email thử tới ${previewEmailDraft.trim()} (${result.candidate_count} ứng viên).`,
          { type: "success" },
        );
      } else if (!result.configured) {
        notify(`Chưa cấu hình đủ: ${result.missing.join(", ")}.`, {
          type: "error",
        });
      } else {
        notify(`Gửi email thử thất bại: ${result.error ?? "không rõ lý do"}`, {
          type: "error",
        });
      }
    },
    onError: () => {
      notify("Không gửi được email thử.", { type: "error" });
    },
  });

  const storedRecipients = settings?.recipients ?? [];
  const recipientsValue = recipientsDraft ?? storedRecipients.join(",\n");
  const frequency: EmailDigestFrequency =
    frequencyDraft ?? settings?.frequency ?? "daily";
  const sendTime = sendTimeDraft ?? settings?.send_time ?? "09:00";
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
    Boolean(trimmedApiKey) ||
    recipientsChanged ||
    frequencyDraft !== null ||
    sendTimeDraft !== null ||
    enabledDraft !== null;

  const configuredFields = [
    settings?.resend_api_key?.configured,
    storedRecipients.length > 0,
  ].filter(Boolean).length;

  const submit = () => {
    if (!settings || isError || saveSettings.isPending || !dirty) return;
    saveSettings.mutate({
      ...(trimmedApiKey ? { resend_api_key: trimmedApiKey } : {}),
      recipients: parsedRecipients,
      frequency,
      send_time: sendTime,
      ...(enabledDraft !== null ? { enabled: enabledDraft } : {}),
    });
  };

  return (
    <SettingsSectionPanel id="settings-email-digest">
      {isError ? (
        <div role="alert" className="mb-3 text-body-sm">
          <p>Chưa tải được cấu hình email.</p>
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
        <legend className="sr-only">Cấu hình email ứng viên mới</legend>
        <SettingsGroup
          className="settings-tingting-card"
          title="Resend & người nhận"
          icon={<Mail className="size-5" aria-hidden="true" />}
          meta={
            <SettingsGroupStatus
              configured={configuredFields}
              total={EMAIL_DIGEST_FIELD_COUNT}
              state={statusState}
            />
          }
          defaultOpen
        >
          <SecretField
            id="email_digest_resend_api_key"
            label="Resend API key"
            placeholder="Nhập Resend API key"
            configured={settings?.resend_api_key?.configured ?? false}
            statusState={statusState}
            preview={settings?.resend_api_key?.preview ?? null}
            value={apiKeyDraft}
            onChange={setApiKeyDraft}
            notify={notify}
            hint="Để trống để giữ key đã lưu. Khi chưa lưu key, hệ thống dùng biến môi trường RESEND_API_KEY."
          />

          <div className="settings-tingting-subhead">
            <h3>Người nhận</h3>
            <p>Danh sách trống = tắt email ứng viên mới.</p>
          </div>
          <label
            htmlFor="email_digest_recipients"
            className="text-body-sm text-foreground"
          >
            Danh sách email người nhận
          </label>
          <Textarea
            id="email_digest_recipients"
            value={recipientsValue}
            onChange={(event) => setRecipientsDraft(event.target.value)}
            placeholder={"hr@congty.vn\nquanly@congty.vn"}
            rows={3}
            className="min-h-10"
          />
          <p className="text-body-xs text-text-substandard">
            Phân tách bằng dấu phẩy hoặc xuống dòng.
          </p>

          <div className="settings-tingting-subhead">
            <h3>Lịch gửi</h3>
            <p>{describeSchedule(frequency, sendTime)}</p>
          </div>
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label="Tần suất gửi"
          >
            {(Object.keys(FREQUENCY_LABELS) as EmailDigestFrequency[]).map(
              (option) => (
                <Button
                  key={option}
                  type="button"
                  size="sm"
                  color={frequency === option ? "primary" : "secondary"}
                  className="uu-scope tt-btn-touch"
                  aria-pressed={frequency === option}
                  onClick={() => setFrequencyDraft(option)}
                >
                  {FREQUENCY_LABELS[option]}
                </Button>
              ),
            )}
            <Select value={sendTime} onValueChange={setSendTimeDraft}>
              <SelectTrigger
                id="email_digest_send_time"
                aria-label="Giờ gửi (giờ Việt Nam)"
                className="h-10 w-32"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SEND_TIMES.map((time) => (
                  <SelectItem key={time} value={time}>
                    {time}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="settings-tingting-subhead">
            <h3>Cron</h3>
            <p>Bật/tắt lịch gửi tự động (không ảnh hưởng nút Gửi email thử).</p>
          </div>
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label="Bật tắt cron"
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

          <div className="settings-tingting-subhead">
            <h3>Gửi email thử</h3>
            <p>
              Gửi thử đúng email người nhận sẽ nhận được — tới một địa chỉ bạn
              nhập, không gửi tới danh sách người nhận.
            </p>
          </div>
          <label
            htmlFor="email_digest_test_recipient"
            className="text-body-sm text-foreground"
          >
            Email nhận thử
          </label>
          <Input
            id="email_digest_test_recipient"
            type="email"
            value={previewEmailDraft}
            onChange={(event) => setPreviewEmailDraft(event.target.value)}
            placeholder="ten@congty.vn"
            className="h-10"
          />
          <div className="settings-tingting-link">
            <span className="settings-tingting-link-copy" role="status">
              {enabled
                ? `Email đang bật. Lần gửi gần nhất: ${
                    formatVietnamDateTime(settings?.last_sent_at) ||
                    "chưa gửi lần nào"
                  } (giờ VN).`
                : enabledDraft === false
                  ? "Email sẽ tắt sau khi bấm Lưu cấu hình."
                  : storedRecipients.length === 0
                    ? "Email đang tắt — thêm ít nhất một người nhận (hoặc bấm Bật cron sau khi có người nhận)."
                    : "Email đang tắt — bấm Bật cron rồi Lưu cấu hình để bật lại."}
            </span>
            <Button
              type="button"
              color="secondary"
              className="uu-scope settings-test-button tt-btn-touch"
              onClick={() => testSend.mutate(previewEmailDraft.trim())}
              isDisabled={testSend.isPending || previewEmailDraft.trim() === ""}
              aria-busy={testSend.isPending}
            >
              {testSend.isPending ? "Đang gửi…" : "Gửi email thử"}
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
              : "Email chỉ gồm ứng viên mới từ Zalo chatbot, Messenger và OA khác — không gồm TingTing OA."}
          </span>
        </div>
      </fieldset>
    </SettingsSectionPanel>
  );
};
