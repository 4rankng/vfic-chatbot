/**
 * Facebook Messenger integration page (Phase 6).
 *
 * Owns the OAuth lifecycle UI: connect a Page via Facebook Login for Business,
 * select one authorized Page, test the connection, and disconnect (which marks
 * the Page inactive and its conversations read-only — history is never deleted).
 *
 * Vietnamese throughout (per project convention). No token/secret/raw PSID ever
 * appears in the UI; the backend projects only a masked page-id suffix + the
 * safe Page label.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useNotify } from "ra-core";
import { Eye, EyeOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import "../conversations/inbox.css";
import "./settings.css";
import {
  facebookIntegrationGateway,
  type FacebookAccountStatus,
  type FacebookChannelTest,
  type FacebookCredentials,
  type FacebookCredentialsUpdate,
  type FacebookIntegrationStatus,
  type FacebookOAuthCompleteRequest,
  type FacebookOAuthStart,
  type FacebookPageList,
} from "./api";
import { consumeFacebookOAuthCallback } from "./facebook-oauth-callback";
import {
  SettingsFieldStatus,
  SettingsGroupStatus,
  type SettingsStatusState,
} from "./SettingsFieldStatus";

type CredentialsFormState = {
  facebook_app_id: string;
  facebook_app_secret: string;
  facebook_login_config_id: string;
  facebook_webhook_verify_token: string;
};

const EMPTY_CREDENTIALS_FORM: CredentialsFormState = {
  facebook_app_id: "",
  facebook_app_secret: "",
  facebook_login_config_id: "",
  facebook_webhook_verify_token: "",
};

// ─── Meta App credentials card ─────────────────────────────────────────────
//
// Lets an admin configure the four app-level Meta credentials (APP_ID,
// APP_SECRET, LOGIN_CONFIG_ID, WEBHOOK_VERIFY_TOKEN) from the UI instead of
// `.env`. Stored DB-first with env fallback on the backend; secrets are
// AES-GCM encrypted at rest. Until app_id is configured, the "Connect"
// button is disabled because Facebook rejects an empty client_id.

type MetaAppFieldProps = {
  id: keyof CredentialsFormState;
  label: string;
  hint?: string;
  configured: boolean;
  showMissingStatus?: boolean;
  statusState?: SettingsStatusState;
  value: string;
  onChange: (key: keyof CredentialsFormState, value: string) => void;
};

const MetaAppPlainField = ({
  id,
  label,
  hint,
  configured,
  showMissingStatus = true,
  statusState = "ready",
  value,
  onChange,
}: MetaAppFieldProps) => (
  <div className="settings-field">
    <div className="settings-field-label-row">
      <Label htmlFor={id}>{label}</Label>
      {showMissingStatus || configured || statusState !== "ready" ? (
        <SettingsFieldStatus configured={configured} state={statusState} />
      ) : null}
    </div>
    <Input
      id={id}
      type="text"
      autoComplete="off"
      spellCheck={false}
      value={value}
      onChange={(event) => onChange(id, event.target.value)}
      className="settings-input"
    />
    {hint ? <span className="settings-field-hint">{hint}</span> : null}
  </div>
);

const MetaAppSecretField = ({
  id,
  label,
  hint,
  configured,
  statusState = "ready",
  preview,
  value,
  onChange,
}: MetaAppFieldProps & {
  configured: boolean;
  preview: string | null;
  statusState?: SettingsStatusState;
}) => {
  const [isVisible, setIsVisible] = useState(false);
  return (
    <div className="settings-field">
      <div className="settings-field-label-row">
        <Label htmlFor={id}>{label}</Label>
        <SettingsFieldStatus configured={configured} state={statusState} />
      </div>
      <div className="settings-sensitive-input">
        <Input
          id={id}
          type={isVisible ? "text" : "password"}
          autoComplete="off"
          spellCheck={false}
          value={value}
          placeholder={preview ? `Hiện tại: ${preview}` : "Nhập giá trị mới"}
          className="settings-input"
          onChange={(event) => onChange(id, event.target.value)}
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
      </div>
      {hint ? <span className="settings-field-hint">{hint}</span> : null}
    </div>
  );
};

// ─── Component ─────────────────────────────────────────────────────────────

export const FacebookMessengerIntegrationPage = () => {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const [pendingFlowId, setPendingFlowId] = useState<string | null>(null);
  const [flowIdDraft, setFlowIdDraft] = useState("");
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [credentialsForm, setCredentialsForm] = useState<CredentialsFormState>(
    EMPTY_CREDENTIALS_FORM,
  );

  useEffect(() => {
    const callback = consumeFacebookOAuthCallback(window.location.hash);
    if (!callback) return;
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}${callback.cleanHash}`,
    );
    setPendingFlowId(callback.flowId);
    setError(callback.errorMessage);
  }, []);

  // Status: active + archived Page accounts.
  const { data: status } = useQuery<FacebookIntegrationStatus>({
    queryKey: ["facebook-integration-status"],
    queryFn: () => facebookIntegrationGateway.loadStatus(),
    staleTime: 30_000,
  });

  // App-level Meta credentials (DB-first, env fallback on the backend).
  const {
    data: credentials,
    isPending: credentialsPending,
    isError: credentialsError,
  } = useQuery<FacebookCredentials>({
    queryKey: ["facebook-credentials"],
    queryFn: () => facebookIntegrationGateway.loadCredentials(),
    staleTime: 30_000,
  });

  const saveCredentials = useMutation<
    FacebookCredentials,
    Error,
    FacebookCredentialsUpdate
  >({
    mutationFn: (body) => facebookIntegrationGateway.saveCredentials(body),
    onSuccess: (data) => {
      setError(null);
      // Reset the form so secret fields go back to "leave blank to keep" mode.
      setCredentialsForm({
        ...EMPTY_CREDENTIALS_FORM,
        facebook_app_id: data.facebook_app_id.value ?? "",
        facebook_login_config_id: data.facebook_login_config_id.value ?? "",
      });
      queryClient.invalidateQueries({
        queryKey: ["facebook-credentials"],
      });
      notify("Đã lưu thông tin ứng dụng Meta.", { type: "success" });
    },
    onError: () => {
      notify("Không thể lưu thông tin ứng dụng Meta.", { type: "error" });
    },
  });

  const onCredentialChange = (
    key: keyof CredentialsFormState,
    value: string,
  ) => {
    setCredentialsForm((form) => ({ ...form, [key]: value }));
  };

  const submitCredentials = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // Only send non-empty fields ("leave blank to keep" semantics).
    const payload: FacebookCredentialsUpdate = {};
    const trimmed: CredentialsFormState = {
      facebook_app_id: credentialsForm.facebook_app_id.trim(),
      facebook_app_secret: credentialsForm.facebook_app_secret.trim(),
      facebook_login_config_id: credentialsForm.facebook_login_config_id.trim(),
      facebook_webhook_verify_token:
        credentialsForm.facebook_webhook_verify_token.trim(),
    };
    (Object.keys(trimmed) as Array<keyof CredentialsFormState>).forEach(
      (key) => {
        if (trimmed[key]) payload[key] = trimmed[key];
      },
    );
    if (Object.keys(payload).length === 0) {
      notify("Chưa có trường nào để lưu.", { type: "info" });
      return;
    }
    saveCredentials.mutate(payload);
  };

  const appIdConfigured = credentials?.facebook_app_id.configured ?? false;
  const credentialsStatusState: SettingsStatusState = credentialsPending
    ? "loading"
    : credentialsError
      ? "error"
      : "ready";
  const configuredCredentialCount = credentials
    ? [
        credentials.facebook_app_id.configured,
        credentials.facebook_app_secret.configured,
        credentials.facebook_webhook_verify_token.configured,
      ].filter(Boolean).length
    : 0;

  // Seed the plaintext (non-secret) fields with the server's current value
  // once on load. Secret fields stay empty ("leave blank to keep current value").
  useEffect(() => {
    if (!credentials) return;
    setCredentialsForm((current) => ({
      ...current,
      facebook_app_id:
        current.facebook_app_id || credentials.facebook_app_id.value || "",
      facebook_login_config_id:
        current.facebook_login_config_id ||
        credentials.facebook_login_config_id.value ||
        "",
    }));
  }, [credentials]);

  // Pages available after OAuth callback (from the flow record).
  const { data: pageList, isError: isPageListError } =
    useQuery<FacebookPageList>({
      queryKey: ["facebook-oauth-pages", pendingFlowId],
      queryFn: () =>
        facebookIntegrationGateway.loadOAuthPages(pendingFlowId ?? ""),
      enabled: pendingFlowId !== null,
      staleTime: 0,
    });

  // Step 1: start OAuth — get the authorization URL and open it.
  const startOAuth = useMutation<FacebookOAuthStart, Error>({
    mutationFn: () => facebookIntegrationGateway.startOAuth(),
    onSuccess: (data) => {
      setError(null);
      // Open the official Facebook authorization URL. The callback redirects
      // back to the frontend with an opaque flow_id; the admin pastes/returns
      // here to complete Page selection.
      window.open(data.authorization_url, "_blank", "noopener");
    },
    onError: () =>
      setError("Không thể bắt đầu kết nối Facebook. Vui lòng thử lại."),
  });

  // Step 4: complete — select one Page, activate it.
  const completeOAuth = useMutation<
    FacebookAccountStatus,
    Error,
    FacebookOAuthCompleteRequest
  >({
    mutationFn: (body) => facebookIntegrationGateway.completeOAuth(body),
    onSuccess: () => {
      setPendingFlowId(null);
      setSelectedPageId(null);
      setError(null);
      queryClient.invalidateQueries({
        queryKey: ["facebook-integration-status"],
      });
    },
    onError: () => {
      setPendingFlowId(null);
      setSelectedPageId(null);
      setError("Kích hoạt Trang thất bại. Vui lòng kết nối lại.");
    },
  });

  // Test the active connection.
  const testConnection = useMutation<FacebookChannelTest, Error>({
    mutationFn: () => facebookIntegrationGateway.testConnection(),
  });

  // Disconnect a Page (marks inactive; history preserved).
  const disconnect = useMutation<FacebookAccountStatus, Error, void>({
    mutationFn: () => facebookIntegrationGateway.disconnect(),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({
        queryKey: ["facebook-integration-status"],
      });
    },
    onError: () => setError("Ngắt kết nối Trang thất bại."),
  });

  const activeAccount = status?.accounts.find((a) => a.status === "ACTIVE");
  const archivedAccounts =
    status?.accounts.filter((a) => a.status !== "ACTIVE") ?? [];

  const loadManualFlow = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const flowId = flowIdDraft.trim();
    if (!flowId) return;
    setSelectedPageId(null);
    setError(null);
    setPendingFlowId(flowId);
  };

  const resetPageSelection = () => {
    setPendingFlowId(null);
    setSelectedPageId(null);
  };

  const needsPageListRecovery =
    pendingFlowId !== null &&
    (isPageListError ||
      (pageList !== undefined && pageList.pages.length === 0));

  return (
    <section
      className="settings-section-panel settings-messenger"
      aria-labelledby="facebook-messenger-settings-title"
    >
      <h2 id="facebook-messenger-settings-title" className="sr-only">
        Facebook Messenger
      </h2>

      {error ? (
        <div
          className="settings-test-result settings-test-result-error tt-alert tt-alert-error tt-alert-soft"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      {/* Meta App credentials (DB-first, env fallback). Required before the
          OAuth flow can build a valid authorization URL. */}
      <form
        className="settings-group settings-messenger-group settings-messenger-credentials"
        onSubmit={submitCredentials}
      >
        <div className="settings-messenger-group-heading">
          <div>
            <h3 className="settings-messenger-group-title">Ứng dụng Meta</h3>
            <p className="settings-field-hint">
              Để trống bí mật để giữ giá trị đã lưu.
            </p>
          </div>
          <SettingsGroupStatus
            configured={configuredCredentialCount}
            total={3}
            state={credentialsStatusState}
          />
        </div>
        <div className="settings-group-content settings-messenger-group-content">
          <div className="settings-messenger-credentials-grid">
            <MetaAppPlainField
              id="facebook_app_id"
              label="App ID"
              configured={credentials?.facebook_app_id.configured ?? false}
              statusState={credentialsStatusState}
              value={credentialsForm.facebook_app_id}
              onChange={onCredentialChange}
            />
            <MetaAppPlainField
              id="facebook_login_config_id"
              label="Configuration ID"
              hint="Không bắt buộc"
              configured={
                credentials?.facebook_login_config_id.configured ?? false
              }
              showMissingStatus={false}
              statusState={credentialsStatusState}
              value={credentialsForm.facebook_login_config_id}
              onChange={onCredentialChange}
            />
            <MetaAppSecretField
              id="facebook_app_secret"
              label="App Secret"
              configured={credentials?.facebook_app_secret.configured ?? false}
              statusState={credentialsStatusState}
              preview={credentials?.facebook_app_secret.preview ?? null}
              value={credentialsForm.facebook_app_secret}
              onChange={onCredentialChange}
            />
            <MetaAppSecretField
              id="facebook_webhook_verify_token"
              label="Verify Token"
              hint="Đổi token? Đăng ký lại webhook trên Meta."
              configured={
                credentials?.facebook_webhook_verify_token.configured ?? false
              }
              statusState={credentialsStatusState}
              preview={
                credentials?.facebook_webhook_verify_token.preview ?? null
              }
              value={credentialsForm.facebook_webhook_verify_token}
              onChange={onCredentialChange}
            />
          </div>
          <div className="settings-oa-actions settings-messenger-actions">
            <Button
              type="submit"
              className="settings-test-button settings-messenger-solid-action tt-btn-touch"
              disabled={saveCredentials.isPending}
              aria-busy={saveCredentials.isPending}
            >
              {saveCredentials.isPending ? "Đang lưu…" : "Lưu thông tin"}
            </Button>
          </div>
        </div>
      </form>

      {/* Active connection */}
      {activeAccount ? (
        <div className="settings-group settings-messenger-group">
          <div className="settings-group-content settings-messenger-group-content">
            <div className="settings-field">
              <span className="settings-field-label">Trang đang kết nối</span>
              <span className="settings-field-value">
                <strong>{activeAccount.label}</strong>{" "}
                <span className="settings-field-hint">
                  (…{activeAccount.page_id_suffix})
                </span>
              </span>
            </div>
            <div className="settings-oa-actions settings-messenger-actions">
              <button
                type="button"
                className="settings-test-button tt-btn-touch"
                onClick={() => testConnection.mutate()}
                disabled={testConnection.isPending}
                aria-busy={testConnection.isPending}
              >
                {testConnection.isPending
                  ? "Đang kiểm tra…"
                  : "Kiểm tra kết nối"}
              </button>
              <button
                type="button"
                className="settings-test-button settings-danger-action tt-btn-touch"
                onClick={() => disconnect.mutate()}
                disabled={disconnect.isPending}
                aria-busy={disconnect.isPending}
              >
                {disconnect.isPending ? "Đang ngắt…" : "Ngắt kết nối"}
              </button>
            </div>
            {testConnection.data ? (
              <div
                className={`settings-test-result settings-messenger-result tt-alert tt-alert-soft ${
                  testConnection.data.healthy
                    ? "settings-test-result-ok tt-alert-success"
                    : "settings-test-result-error tt-alert-error"
                }`}
              >
                {testConnection.data.healthy
                  ? "Kết nối Messenger hoạt động bình thường; webhook đang nhận sự kiện từ Trang."
                  : (testConnection.data.error ?? "Kết nối không khả dụng.")}
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="settings-group settings-messenger-group">
          <div className="settings-group-content settings-messenger-group-content settings-messenger-empty">
            <div className="settings-messenger-empty-copy">
              <h3 className="settings-messenger-group-title">Chưa kết nối</h3>
              <p className="settings-field-hint">
                {appIdConfigured
                  ? "Kết nối một Trang để nhận tin nhắn."
                  : "Nhập App ID trước khi kết nối."}
              </p>
            </div>
            <button
              type="button"
              className="settings-test-button settings-messenger-primary-action settings-messenger-solid-action tt-btn-touch"
              onClick={() => startOAuth.mutate()}
              disabled={startOAuth.isPending || !appIdConfigured}
              aria-busy={startOAuth.isPending}
              title={
                appIdConfigured
                  ? undefined
                  : "Cấu hình App ID trước khi kết nối"
              }
            >
              {startOAuth.isPending ? "Đang chuẩn bị…" : "Kết nối Facebook"}
            </button>
          </div>
        </div>
      )}

      {/* Page selection after OAuth callback */}
      {pendingFlowId && pageList?.pages && pageList.pages.length > 0 ? (
        <div className="settings-group settings-messenger-group">
          <div className="settings-group-content settings-messenger-group-content">
            <h3 className="settings-messenger-group-title">
              Chọn Trang để kích hoạt
            </h3>
            <ul className="settings-page-list">
              {pageList.pages.map((page) => (
                <li key={page.id}>
                  <label>
                    <input
                      className="tt-radio tt-radio-primary tt-radio-sm"
                      type="radio"
                      name="facebook-page"
                      value={page.id}
                      checked={selectedPageId === page.id}
                      onChange={() => setSelectedPageId(page.id)}
                    />
                    <span>{page.name}</span>
                  </label>
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="settings-test-button settings-messenger-primary-action settings-messenger-solid-action tt-btn-touch"
              onClick={() =>
                selectedPageId &&
                completeOAuth.mutate({
                  flow_id: pendingFlowId,
                  page_id: selectedPageId,
                })
              }
              disabled={!selectedPageId || completeOAuth.isPending}
              aria-busy={completeOAuth.isPending}
            >
              {completeOAuth.isPending ? "Đang kích hoạt…" : "Kích hoạt Trang"}
            </button>
          </div>
        </div>
      ) : null}

      {needsPageListRecovery ? (
        <div
          className="settings-test-result settings-test-result-error tt-alert tt-alert-error tt-alert-soft"
          role="alert"
        >
          <p>
            {isPageListError
              ? "Không thể tải danh sách Trang. Mã phiên có thể không hợp lệ hoặc đã hết hạn."
              : "Không tìm thấy Trang Facebook nào trong phiên kết nối này."}
          </p>
          <p>Vui lòng kết nối lại hoặc nhập một mã phiên khác.</p>
          <button
            type="button"
            className="settings-test-button tt-btn-touch"
            onClick={resetPageSelection}
          >
            Quay lại kết nối
          </button>
        </div>
      ) : null}

      {/* Manual flow-id entry (after OAuth redirect back to frontend) */}
      {!activeAccount && !pendingFlowId ? (
        <details className="settings-group settings-messenger-recovery tt-collapse tt-collapse-arrow">
          <summary className="settings-messenger-recovery-summary tt-collapse-title">
            Nhập mã phiên OAuth
          </summary>
          <div className="settings-messenger-recovery-content tt-collapse-content">
            <form
              className="settings-field settings-messenger-recovery-form"
              onSubmit={loadManualFlow}
            >
              <label
                className="settings-field-label"
                htmlFor="facebook-oauth-flow-id"
              >
                Mã phiên OAuth
              </label>
              <input
                className="tt-input"
                id="facebook-oauth-flow-id"
                name="facebook-oauth-flow-id"
                type="text"
                autoComplete="off"
                spellCheck={false}
                value={flowIdDraft}
                onChange={(event) => setFlowIdDraft(event.target.value)}
              />
              <span className="settings-field-hint">
                Dùng để tải các Trang đã ủy quyền.
              </span>
              <button
                type="submit"
                className="settings-test-button settings-messenger-solid-action tt-btn-touch"
                disabled={!flowIdDraft.trim()}
              >
                Tải danh sách Trang
              </button>
            </form>
          </div>
        </details>
      ) : null}

      {/* Archived Page scopes (read-only history) */}
      {archivedAccounts.length > 0 ? (
        <div className="settings-group settings-messenger-group">
          <div className="settings-group-content settings-messenger-group-content">
            <h3 className="settings-messenger-group-title">
              Trang đã ngắt kết nối
            </h3>
            <p className="settings-field-hint">
              Lịch sử hội thoại được giữ lại (chỉ xem). Kết nối lại cùng Trang
              để tiếp tục trả lời.
            </p>
            <ul className="settings-page-list">
              {archivedAccounts.map((a) => (
                <li key={a.page_id_suffix}>
                  <span>{a.label}</span>{" "}
                  <span className="settings-field-hint">
                    (…{a.page_id_suffix}) ·{" "}
                    {a.status === "INACTIVE" ? "Chỉ xem" : a.status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </section>
  );
};
