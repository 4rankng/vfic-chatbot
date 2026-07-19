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
import { apiJson } from "../providers/rest/api";
import "../conversations/inbox.css";
import "./settings.css";

// ─── API types (mirror the backend Pydantic schemas) ───────────────────────

type FacebookAccountStatus = {
  page_id_suffix: string;
  label: string;
  status: "ACTIVE" | "INACTIVE";
};

type FacebookIntegrationStatus = {
  enabled: boolean;
  accounts: FacebookAccountStatus[];
};

type FacebookOAuthStart = {
  authorization_url: string;
};

type FacebookPage = {
  id: string;
  name: string;
};

type FacebookPageList = {
  pages: FacebookPage[];
  active_page_id: string | null;
};

type FacebookOAuthCompleteRequest = {
  flow_id: string;
  page_id: string;
};

type FacebookChannelTest = {
  healthy: boolean;
  error: string | null;
};

// App-level Meta credentials (configurable via the admin UI). Mirrors the
// backend SecretStatus / PlainStatus shape.
type SecretStatus = {
  configured: boolean;
  preview: string | null;
};

type PlainStatus = {
  configured: boolean;
  value: string | null;
};

type FacebookCredentials = {
  facebook_app_id: PlainStatus;
  facebook_app_secret: SecretStatus;
  facebook_login_config_id: PlainStatus;
  facebook_webhook_verify_token: SecretStatus;
};

type FacebookCredentialsUpdate = {
  facebook_app_id?: string;
  facebook_app_secret?: string;
  facebook_login_config_id?: string;
  facebook_webhook_verify_token?: string;
};

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

const FACEBOOK_OAUTH_CALLBACK_KEYS = [
  "facebook_oauth_status",
  "facebook_oauth_flow_id",
  "facebook_oauth_error",
] as const;

const FACEBOOK_OAUTH_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  invalid_state:
    "Phiên kết nối không hợp lệ hoặc đã hết hạn. Vui lòng kết nối lại.",
  invalid_admin: "Tài khoản quản trị không còn hợp lệ. Vui lòng đăng nhập lại.",
  session_changed:
    "Phiên đăng nhập đã thay đổi. Vui lòng đăng nhập và kết nối lại.",
  missing_code: "Facebook không trả về mã ủy quyền. Vui lòng thử kết nối lại.",
  exchange_failed:
    "Không thể hoàn tất ủy quyền Facebook. Vui lòng thử kết nối lại.",
  no_pages: "Không tìm thấy Trang Facebook có thể kết nối.",
};

const GENERIC_OAUTH_ERROR =
  "Không thể hoàn tất kết nối Facebook. Vui lòng thử lại.";

type FacebookOAuthCallback = {
  flowId: string | null;
  errorMessage: string | null;
};

const consumeFacebookOAuthCallback = (): FacebookOAuthCallback | null => {
  const hash = window.location.hash;
  const queryIndex = hash.indexOf("?");
  if (queryIndex === -1) return null;

  const hashPath = hash.slice(0, queryIndex);
  const params = new URLSearchParams(hash.slice(queryIndex + 1));
  if (!FACEBOOK_OAUTH_CALLBACK_KEYS.some((key) => params.has(key))) return null;

  const status = params.get("facebook_oauth_status");
  const callbackFlowId = params.get("facebook_oauth_flow_id")?.trim() ?? "";
  const errorCode = params.get("facebook_oauth_error") ?? "";

  FACEBOOK_OAUTH_CALLBACK_KEYS.forEach((key) => params.delete(key));
  const cleanQuery = params.toString();
  const cleanHash = cleanQuery ? `${hashPath}?${cleanQuery}` : hashPath;
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${window.location.search}${cleanHash}`,
  );

  if (status === "pending_selection" && callbackFlowId) {
    return { flowId: callbackFlowId, errorMessage: null };
  }
  if (status === "error") {
    return {
      flowId: null,
      errorMessage:
        FACEBOOK_OAUTH_ERROR_MESSAGES[errorCode] ?? GENERIC_OAUTH_ERROR,
    };
  }
  return { flowId: null, errorMessage: GENERIC_OAUTH_ERROR };
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
  value: string;
  onChange: (key: keyof CredentialsFormState, value: string) => void;
};

const MetaAppPlainField = ({
  id,
  label,
  hint,
  value,
  onChange,
}: MetaAppFieldProps) => (
  <div className="settings-field">
    <Label htmlFor={id}>{label}</Label>
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
  preview,
  value,
  onChange,
}: MetaAppFieldProps & {
  configured: boolean;
  preview: string | null;
}) => {
  const [isVisible, setIsVisible] = useState(false);
  return (
    <div className="settings-field">
      <div className="settings-field-label-row">
        <Label htmlFor={id}>{label}</Label>
        <span className={configured ? "is-configured" : ""}>
          {configured ? "Đã lưu" : "Chưa cấu hình"}
        </span>
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
    const callback = consumeFacebookOAuthCallback();
    if (!callback) return;
    setPendingFlowId(callback.flowId);
    setError(callback.errorMessage);
  }, []);

  // Status: active + archived Page accounts.
  const { data: status } = useQuery<FacebookIntegrationStatus>({
    queryKey: ["facebook-integration-status"],
    queryFn: () =>
      apiJson<FacebookIntegrationStatus>("/api/v1/admin/integrations/facebook"),
    staleTime: 30_000,
  });

  // App-level Meta credentials (DB-first, env fallback on the backend).
  const { data: credentials } = useQuery<FacebookCredentials>({
    queryKey: ["facebook-credentials"],
    queryFn: () =>
      apiJson<FacebookCredentials>(
        "/api/v1/admin/integrations/facebook/credentials",
      ),
    staleTime: 30_000,
  });

  const saveCredentials = useMutation<
    FacebookCredentials,
    Error,
    FacebookCredentialsUpdate
  >({
    mutationFn: (body) =>
      apiJson<FacebookCredentials>(
        "/api/v1/admin/integrations/facebook/credentials",
        { method: "PUT", body },
      ),
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
        apiJson<FacebookPageList>(
          `/api/v1/admin/integrations/facebook/oauth/pages?flow_id=${encodeURIComponent(pendingFlowId ?? "")}`,
        ),
      enabled: pendingFlowId !== null,
      staleTime: 0,
    });

  // Step 1: start OAuth — get the authorization URL and open it.
  const startOAuth = useMutation<FacebookOAuthStart, Error>({
    mutationFn: () =>
      apiJson<FacebookOAuthStart>(
        "/api/v1/admin/integrations/facebook/oauth/start",
        {
          method: "POST",
        },
      ),
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
    mutationFn: (body) =>
      apiJson<FacebookAccountStatus>(
        "/api/v1/admin/integrations/facebook/oauth/complete",
        { method: "POST", body },
      ),
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
    mutationFn: () =>
      apiJson<FacebookChannelTest>("/api/v1/admin/integrations/facebook/test", {
        method: "POST",
      }),
  });

  // Disconnect a Page (marks inactive; history preserved).
  const disconnect = useMutation<FacebookAccountStatus, Error, void>({
    mutationFn: () =>
      apiJson<FacebookAccountStatus>("/api/v1/admin/integrations/facebook", {
        method: "DELETE",
      }),
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
        className="settings-card settings-messenger-card tt-card tt-card-border"
        onSubmit={submitCredentials}
      >
        <div className="settings-card-content settings-messenger-card-content">
          <div className="settings-messenger-card-heading">
            <h3 className="settings-messenger-card-title">Ứng dụng Meta</h3>
            <p className="settings-field-hint">
              Để trống bí mật để giữ giá trị đã lưu.
            </p>
          </div>
          <div className="settings-messenger-credentials-grid">
            <MetaAppPlainField
              id="facebook_app_id"
              label="App ID"
              value={credentialsForm.facebook_app_id}
              onChange={onCredentialChange}
            />
            <MetaAppPlainField
              id="facebook_login_config_id"
              label="Configuration ID"
              hint="Không bắt buộc"
              value={credentialsForm.facebook_login_config_id}
              onChange={onCredentialChange}
            />
            <MetaAppSecretField
              id="facebook_app_secret"
              label="App Secret"
              configured={credentials?.facebook_app_secret.configured ?? false}
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
              className="settings-test-button settings-messenger-solid-action tt-btn tt-btn-primary tt-btn-sm"
              disabled={saveCredentials.isPending}
            >
              {saveCredentials.isPending ? "Đang lưu…" : "Lưu thông tin"}
            </Button>
          </div>
        </div>
      </form>

      {/* Active connection */}
      {activeAccount ? (
        <div className="settings-card settings-messenger-card tt-card tt-card-border">
          <div className="settings-card-content settings-messenger-card-content">
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
                className="settings-test-button tt-btn tt-btn-outline tt-btn-sm"
                onClick={() => testConnection.mutate()}
                disabled={testConnection.isPending}
              >
                {testConnection.isPending
                  ? "Đang kiểm tra…"
                  : "Kiểm tra kết nối"}
              </button>
              <button
                type="button"
                className="settings-test-button tt-btn tt-btn-error tt-btn-outline tt-btn-sm"
                onClick={() => disconnect.mutate()}
                disabled={disconnect.isPending}
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
                  ? "Kết nối Messenger hoạt động bình thường."
                  : (testConnection.data.error ?? "Kết nối không khả dụng.")}
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="settings-card settings-messenger-card tt-card tt-card-border">
          <div className="settings-card-content settings-messenger-card-content settings-messenger-empty">
            <div className="settings-messenger-empty-copy">
              <h3 className="settings-messenger-card-title">Chưa kết nối</h3>
              <p className="settings-field-hint">
                {appIdConfigured
                  ? "Kết nối một Trang để nhận tin nhắn."
                  : "Nhập App ID trước khi kết nối."}
              </p>
            </div>
            <button
              type="button"
              className="settings-test-button settings-messenger-primary-action settings-messenger-solid-action tt-btn tt-btn-primary tt-btn-sm"
              onClick={() => startOAuth.mutate()}
              disabled={startOAuth.isPending || !appIdConfigured}
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
        <div className="settings-card settings-messenger-card tt-card tt-card-border">
          <div className="settings-card-content settings-messenger-card-content">
            <h3 className="settings-messenger-card-title">
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
              className="settings-test-button settings-messenger-primary-action settings-messenger-solid-action tt-btn tt-btn-primary tt-btn-sm"
              onClick={() =>
                selectedPageId &&
                completeOAuth.mutate({
                  flow_id: pendingFlowId,
                  page_id: selectedPageId,
                })
              }
              disabled={!selectedPageId || completeOAuth.isPending}
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
            className="settings-test-button tt-btn tt-btn-outline tt-btn-sm"
            onClick={resetPageSelection}
          >
            Quay lại kết nối
          </button>
        </div>
      ) : null}

      {/* Manual flow-id entry (after OAuth redirect back to frontend) */}
      {!activeAccount && !pendingFlowId ? (
        <details className="settings-card settings-messenger-recovery tt-collapse tt-collapse-arrow tt-card tt-card-border">
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
                className="settings-test-button settings-messenger-solid-action tt-btn tt-btn-primary tt-btn-sm"
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
        <div className="settings-card settings-messenger-card tt-card tt-card-border">
          <div className="settings-card-content settings-messenger-card-content">
            <h3 className="settings-messenger-card-title">
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
