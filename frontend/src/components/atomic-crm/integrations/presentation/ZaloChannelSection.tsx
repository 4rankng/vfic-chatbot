import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, PlugZap, Unlink, Wifi } from "lucide-react";
import { useNotify, useTranslate } from "ra-core";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import {
  zaloIntegrationGateway,
  type SecretStatus,
  type ZaloOaAccount,
  type ZaloOaAccountLinkRequest,
  type ZaloOaAccounts,
  type ZaloOaSignatureHealth,
  type ZaloSettings,
} from "../api";
import type { SettingsStatusState } from "../SettingsFieldStatus";
import { SettingsGroupStatus } from "../SettingsFieldStatus";
import type { ZaloChannelScope } from "../application/useZaloForm";
import type { ZaloFormState } from "../zaloUpdatePayload";
import type { CredentialFieldNotify } from "./credentialClipboard";
import { PlainField, SecretField } from "./SecretField";
import { SettingsGroup, SettingsSectionPanel } from "./SettingsGroup";
import { formatRelativeEpoch } from "./statusCopy";

const describeOaSignatureHealth = (health: ZaloOaSignatureHealth | null) => {
  if (!health || !health.last_status) {
    return {
      message:
        "Chưa có sự kiện webhook thực nào — trạng thái chữ ký sẽ cập nhật khi Zalo gửi tin nhắn đầu tiên.",
      type: "info" as const,
    };
  }
  if (health.last_status === "verified") {
    return {
      message: `Chữ ký webhook hợp lệ — cập nhật ${formatRelativeEpoch(health.last_ts)}.`,
      type: "success" as const,
    };
  }
  return {
    message: `Chữ ký webhook bị từ chối — Webhook Secret có thể sai${health.consec_failures ? ` (×${health.consec_failures})` : ""}. Cập nhật ${formatRelativeEpoch(health.last_mismatch_ts ?? health.last_ts)}.`,
    type: "warning" as const,
  };
};

const OA_ACCOUNTS_QUERY_KEY = ["zalo-oa-accounts"] as const;

const ZALO_OA_STATUS_LABELS: Readonly<
  Record<ZaloOaAccount["status"], string>
> = {
  ACTIVE: "Đang hoạt động",
  INACTIVE: "Tạm dừng",
};

/** Local draft of the link form; every field is a string while typing. */
type ZaloOaLinkForm = {
  oa_id: string;
  label: string;
  app_id: string;
  secret_key: string;
  access_token: string;
  refresh_token: string;
};

const EMPTY_OA_LINK_FORM: ZaloOaLinkForm = {
  oa_id: "",
  label: "",
  app_id: "",
  secret_key: "",
  access_token: "",
  refresh_token: "",
};

/**
 * Build the POST body: empty optional credentials are omitted entirely rather
 * than sent as "", so a link never clears an unrelated field server-side.
 */
const buildZaloOaLinkRequest = (
  form: ZaloOaLinkForm,
): ZaloOaAccountLinkRequest => {
  const request: ZaloOaAccountLinkRequest = {
    oa_id: form.oa_id.trim(),
    label: form.label.trim(),
    access_token: form.access_token.trim(),
  };
  const appId = form.app_id.trim();
  const secretKey = form.secret_key.trim();
  const refreshToken = form.refresh_token.trim();
  if (appId) request.app_id = appId;
  if (secretKey) request.secret_key = secretKey;
  if (refreshToken) request.refresh_token = refreshToken;
  return request;
};

/** The API exposes only a masked tail, never the raw secret. */
const describeStoredCredential = (status: SecretStatus): string => {
  if (!status.configured) return "chưa cấu hình";
  return status.preview ? `đã lưu (${status.preview})` : "đã lưu";
};

const OaLinkField = ({
  id,
  label,
  value,
  onChange,
  type = "text",
  required = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "password";
  required?: boolean;
}) => (
  <div className="settings-field">
    <div className="settings-field-label-row">
      <Label htmlFor={id}>{label}</Label>
    </div>
    <Input
      id={id}
      type={type}
      autoComplete="off"
      spellCheck={false}
      required={required}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="settings-input"
    />
  </div>
);

/**
 * Multi-OA management block: the linked OAs (default+linked), a link form and a
 * per-row unlink. The seeded `default:zalo_oa` is never unlinkable.
 */
const ZaloOaAccountsPanel = ({ notify }: { notify: CredentialFieldNotify }) => {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ZaloOaLinkForm>(EMPTY_OA_LINK_FORM);

  const { data, isPending, isError } = useQuery<ZaloOaAccounts>({
    queryKey: OA_ACCOUNTS_QUERY_KEY,
    queryFn: () => zaloIntegrationGateway.listZaloOaAccounts(),
    staleTime: 30_000,
  });

  const linkAccount = useMutation<
    ZaloOaAccounts,
    Error,
    ZaloOaAccountLinkRequest
  >({
    mutationFn: (body) => zaloIntegrationGateway.linkZaloOaAccount(body),
    onSuccess: (accounts) => {
      // The mutation response is the new truth for the list.
      queryClient.setQueryData(OA_ACCOUNTS_QUERY_KEY, accounts);
      setForm(EMPTY_OA_LINK_FORM);
      notify("Đã liên kết Zalo OA.", { type: "success" });
    },
    onError: (error) =>
      notify(
        error instanceof Error ? error.message : "Không thể liên kết Zalo OA.",
        { type: "error" },
      ),
  });

  const unlinkAccount = useMutation<ZaloOaAccounts, Error, string>({
    mutationFn: (accountKey) =>
      zaloIntegrationGateway.unlinkZaloOaAccount(accountKey),
    onSuccess: (accounts) => {
      queryClient.setQueryData(OA_ACCOUNTS_QUERY_KEY, accounts);
      notify("Đã gỡ liên kết Zalo OA.", { type: "success" });
    },
    onError: (error) =>
      notify(
        error instanceof Error
          ? error.message
          : "Không thể gỡ liên kết Zalo OA.",
        { type: "error" },
      ),
  });

  const setField = (key: keyof ZaloOaLinkForm, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  const request = buildZaloOaLinkRequest(form);
  const canSubmit =
    request.oa_id !== "" &&
    request.access_token !== "" &&
    !linkAccount.isPending;

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    linkAccount.mutate(request);
  };

  const accounts = data?.accounts ?? [];

  return (
    <div className="settings-oa-linked mt-4 grid gap-3 border-t border-border pt-4">
      <div>
        <div className="text-sm font-semibold text-foreground">
          Zalo OA đã liên kết
        </div>
        <p className="text-muted-foreground text-xs">
          OA gốc luôn được giữ và không thể gỡ liên kết.
        </p>
      </div>

      {isPending ? (
        <p className="text-muted-foreground text-sm" role="status">
          Đang tải danh sách OA…
        </p>
      ) : null}
      {isError ? (
        <p className="text-destructive text-sm" role="alert">
          Không tải được danh sách Zalo OA. Vui lòng thử lại.
        </p>
      ) : null}
      {!isPending && !isError && accounts.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          Chưa có Zalo OA nào được liên kết.
        </p>
      ) : null}

      {accounts.length > 0 ? (
        <ul className="grid list-none gap-3 p-0">
          {accounts.map((account) => (
            <li
              key={account.account_key}
              className="grid gap-2 rounded-lg border border-border bg-card p-3"
            >
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <strong className="text-foreground text-sm">
                  {account.label}
                </strong>
                <span className="text-muted-foreground text-xs">
                  {account.account_key}
                </span>
                {account.is_default ? (
                  <span className="text-xs font-semibold text-muted-foreground">
                    OA gốc
                  </span>
                ) : null}
                <span
                  className={
                    account.status === "ACTIVE"
                      ? "text-xs font-semibold text-[var(--success)]"
                      : "text-xs font-semibold text-muted-foreground"
                  }
                >
                  {ZALO_OA_STATUS_LABELS[account.status]}
                </span>
              </div>

              <dl className="grid gap-1 text-xs text-muted-foreground">
                <div className="flex gap-2">
                  <dt className="font-medium">App ID:</dt>
                  <dd>{account.app_id || "chưa cấu hình"}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="font-medium">Secret Key:</dt>
                  <dd>{describeStoredCredential(account.secret_key)}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="font-medium">Access Token:</dt>
                  <dd>{describeStoredCredential(account.access_token)}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="font-medium">Refresh Token:</dt>
                  <dd>{describeStoredCredential(account.refresh_token)}</dd>
                </div>
              </dl>

              {!account.is_default ? (
                <div className="flex justify-end">
                  <Button
                    type="button"
                    variant="ghost"
                    className="settings-danger-action tt-btn-touch"
                    disabled={unlinkAccount.isPending}
                    aria-busy={unlinkAccount.isPending}
                    onClick={() => unlinkAccount.mutate(account.account_key)}
                  >
                    <Unlink className="size-4" />
                    {unlinkAccount.isPending ? "Đang gỡ…" : "Gỡ liên kết"}
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      <form className="grid gap-3 sm:grid-cols-2" onSubmit={onSubmit}>
        <OaLinkField
          id="zalo_oa_link_oa_id"
          label="Mã OA"
          value={form.oa_id}
          onChange={(value) => setField("oa_id", value)}
          required
        />
        <OaLinkField
          id="zalo_oa_link_label"
          label="Tên hiển thị"
          value={form.label}
          onChange={(value) => setField("label", value)}
        />
        <OaLinkField
          id="zalo_oa_link_app_id"
          label="App ID"
          value={form.app_id}
          onChange={(value) => setField("app_id", value)}
        />
        <OaLinkField
          id="zalo_oa_link_secret_key"
          label="Secret Key"
          type="password"
          value={form.secret_key}
          onChange={(value) => setField("secret_key", value)}
        />
        <OaLinkField
          id="zalo_oa_link_access_token"
          label="Access Token"
          type="password"
          value={form.access_token}
          onChange={(value) => setField("access_token", value)}
          required
        />
        <OaLinkField
          id="zalo_oa_link_refresh_token"
          label="Refresh Token"
          type="password"
          value={form.refresh_token}
          onChange={(value) => setField("refresh_token", value)}
        />
        <div className="sm:col-span-2 flex justify-end">
          <Button
            type="submit"
            className="settings-primary-action tt-btn-touch"
            disabled={!canSubmit}
            aria-busy={linkAccount.isPending}
          >
            {linkAccount.isPending ? "Đang liên kết…" : "Liên kết OA"}
          </Button>
        </div>
      </form>
    </div>
  );
};

/** The Zalo channel view: Bot Platform and OA credentials, plus channel tests. */
export const ZaloChannelSection = ({
  settings,
  statusState,
  form,
  onValueChange,
  channelTesting,
  onTestChannel,
}: {
  settings: ZaloSettings | null;
  statusState: SettingsStatusState;
  form: ZaloFormState;
  onValueChange: (key: keyof ZaloFormState, value: string) => void;
  channelTesting: Record<ZaloChannelScope, boolean>;
  onTestChannel: (scope: ZaloChannelScope) => void;
}) => {
  const notify = useNotify();
  const translate = useTranslate();
  const webhookHealth = describeOaSignatureHealth(
    settings?.zalo_oa_webhook_signature ?? null,
  );
  const botConfigured = [
    settings?.zalo_bot_token.configured,
    settings?.zalo_bot_webhook_secret.configured,
  ].filter(Boolean).length;
  const oaConfigured = [
    settings?.zalo_oa_app_id.configured,
    settings?.zalo_oa_secret_key.configured,
    settings?.zalo_oa_access_token.configured,
    settings?.zalo_oa_refresh_token.configured,
  ].filter(Boolean).length;

  return (
    <SettingsSectionPanel id="settings-zalo-channel">
      <div className="settings-grid settings-grid-zalo">
        <SettingsGroup
          title="Zalo Chatbot"
          icon={<PlugZap className="size-4" />}
          meta={
            <SettingsGroupStatus
              configured={botConfigured}
              total={2}
              state={statusState}
            />
          }
          defaultOpen
        >
          <SecretField
            id="zalo_bot_token"
            label="Bot Token"
            placeholder="Nhập giá trị"
            statusState={statusState}
            configured={settings?.zalo_bot_token.configured ?? false}
            preview={settings?.zalo_bot_token.preview ?? null}
            value={form.zalo_bot_token}
            onChange={(value) => onValueChange("zalo_bot_token", value)}
            notify={notify}
          />
          <SecretField
            id="zalo_bot_webhook_secret"
            label="Bot Secret"
            placeholder="Nhập giá trị"
            statusState={statusState}
            configured={settings?.zalo_bot_webhook_secret.configured ?? false}
            preview={settings?.zalo_bot_webhook_secret.preview ?? null}
            value={form.zalo_bot_webhook_secret}
            onChange={(value) =>
              onValueChange("zalo_bot_webhook_secret", value)
            }
            notify={notify}
          />
          <div className="settings-oa-actions">
            <Button
              type="button"
              className="settings-test-button settings-primary-action tt-btn-touch"
              onClick={() => onTestChannel("bot")}
              disabled={channelTesting.bot || !settings}
              aria-busy={channelTesting.bot}
            >
              <Wifi className="size-4" />
              {channelTesting.bot
                ? translate("crm.common.testing")
                : "Lưu & kiểm tra"}
            </Button>
          </div>
        </SettingsGroup>

        <SettingsGroup
          title="Zalo OA"
          icon={<MessageCircle className="size-4" />}
          meta={
            <SettingsGroupStatus
              configured={oaConfigured}
              total={4}
              state={statusState}
            />
          }
        >
          <div className="settings-oa-fields">
            <PlainField
              id="zalo_oa_app_id"
              label="Zalo App ID"
              configured={settings?.zalo_oa_app_id.configured ?? false}
              statusState={statusState}
              value={form.zalo_oa_app_id}
              onChange={(value) => onValueChange("zalo_oa_app_id", value)}
              notify={notify}
            />

            <SecretField
              id="zalo_oa_secret_key"
              label="Bot Secret"
              placeholder="Nhập giá trị"
              statusState={statusState}
              configured={settings?.zalo_oa_secret_key.configured ?? false}
              preview={settings?.zalo_oa_secret_key.preview ?? null}
              value={form.zalo_oa_secret_key}
              onChange={(value) => onValueChange("zalo_oa_secret_key", value)}
              notify={notify}
            />
            <SecretField
              id="zalo_oa_access_token"
              label="OA Access Token"
              placeholder="Nhập giá trị"
              statusState={statusState}
              configured={settings?.zalo_oa_access_token.configured ?? false}
              preview={settings?.zalo_oa_access_token.preview ?? null}
              value={form.zalo_oa_access_token}
              onChange={(value) => onValueChange("zalo_oa_access_token", value)}
              notify={notify}
            />
            <SecretField
              id="zalo_oa_refresh_token"
              label="OA Refresh Token"
              placeholder="Nhập giá trị"
              statusState={statusState}
              configured={settings?.zalo_oa_refresh_token.configured ?? false}
              preview={settings?.zalo_oa_refresh_token.preview ?? null}
              value={form.zalo_oa_refresh_token}
              onChange={(value) =>
                onValueChange("zalo_oa_refresh_token", value)
              }
              notify={notify}
            />
            <div className="settings-oa-actions">
              <Button
                type="button"
                className="settings-test-button settings-primary-action tt-btn-touch"
                onClick={() => onTestChannel("oa")}
                disabled={channelTesting.oa || !settings}
                aria-busy={channelTesting.oa}
              >
                <Wifi className="size-4" />
                {channelTesting.oa
                  ? translate("crm.common.testing")
                  : "Lưu & kiểm tra"}
              </Button>
            </div>
            <details className="settings-advanced settings-webhook-health tt-collapse tt-collapse-arrow">
              <summary className="settings-advanced-summary tt-collapse-title">
                Webhook
              </summary>
              <p
                className={`settings-webhook-message is-${webhookHealth.type}`}
                role="status"
              >
                {webhookHealth.message}
              </p>
            </details>
          </div>
          <ZaloOaAccountsPanel notify={notify} />
        </SettingsGroup>
      </div>
    </SettingsSectionPanel>
  );
};
