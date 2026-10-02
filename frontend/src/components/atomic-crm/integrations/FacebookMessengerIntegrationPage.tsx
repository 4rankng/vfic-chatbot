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
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useGetList, useNotify, useTranslate } from "ra-core";
import { ApiError } from "@/lib/apiClient";

import { AlertFloating } from "@/components/application/alerts/alerts";
import { Button } from "@/components/base/buttons/button";
import { InputBase } from "@/components/base/input/input";
import type { Project } from "../types";
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
  FacebookPageCard,
  FacebookProjectCheckboxList,
} from "./FacebookMessengerPageCard";
import {
  SettingsGroupStatus,
  type SettingsStatusState,
} from "./SettingsFieldStatus";
import { PlainField, SecretField } from "./SecretField";

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

// ─── Component ─────────────────────────────────────────────────────────────

export const FacebookMessengerIntegrationPage = () => {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const translate = useTranslate();
  const [pendingFlowId, setPendingFlowId] = useState<string | null>(null);
  const [flowIdDraft, setFlowIdDraft] = useState("");
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  // Projects picked for the NEW Page during the connect flow; committed
  // atomically with activation via complete (D1 gate — backend 409s when the
  // result would leave the Page with zero ACTIVE-project mappings).
  const [pickerProjectIds, setPickerProjectIds] = useState<string[]>([]);
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
  const statusQuery = useQuery<FacebookIntegrationStatus>({
    queryKey: ["facebook-integration-status"],
    queryFn: () => facebookIntegrationGateway.loadStatus(),
    staleTime: 30_000,
  });
  const { data: status } = statusQuery;

  // Active Projects: options for the per-Page assignment editor (D3).
  const { data: projects = [] } = useGetList<Project>("projects", {
    pagination: { page: 1, perPage: 100 },
    sort: { field: "name", order: "ASC" },
    filter: {},
  });
  const activeProjects = useMemo(
    () => projects.filter((project) => project.is_active),
    [projects],
  );

  // App-level Meta credentials (DB-first, env fallback on the backend).
  const credentialsQuery = useQuery<FacebookCredentials>({
    queryKey: ["facebook-credentials"],
    queryFn: () => facebookIntegrationGateway.loadCredentials(),
    staleTime: 30_000,
  });
  const {
    data: credentials,
    isPending: credentialsPending,
    isError: credentialsError,
  } = credentialsQuery;

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

  // Fetched per reveal rather than cached: the plaintext should not outlive the
  // moment an admin actually asked to see it.
  const revealCredential = async (
    key: "facebook_app_secret" | "facebook_webhook_verify_token",
  ): Promise<string | null> => {
    try {
      return (await facebookIntegrationGateway.revealCredentials())[key];
    } catch {
      notify("Không thể hiển thị giá trị đã lưu.", { type: "error" });
      return null;
    }
  };
  const revealAppSecret = () => revealCredential("facebook_app_secret");
  const revealVerifyToken = () =>
    revealCredential("facebook_webhook_verify_token");

  const submitCredentials = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saveCredentials.isPending || credentialsPending || credentialsError)
      return;
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

  // Step 4: complete — select one Page, assign Projects, activate it.
  const completeOAuth = useMutation<
    FacebookAccountStatus,
    Error,
    FacebookOAuthCompleteRequest
  >({
    mutationFn: (body) => facebookIntegrationGateway.completeOAuth(body),
    onSuccess: () => {
      setPendingFlowId(null);
      setSelectedPageId(null);
      setPickerProjectIds([]);
      setError(null);
      queryClient.invalidateQueries({
        queryKey: ["facebook-integration-status"],
      });
    },
    onError: (err) => {
      setPendingFlowId(null);
      setSelectedPageId(null);
      setPickerProjectIds([]);
      // Surface the backend's reason (e.g. D1: activation requires ≥1 assigned
      // Project) when it provides a friendly detail; fall back to generic copy.
      setError(
        err instanceof ApiError
          ? err.message
          : "Kích hoạt Trang thất bại. Vui lòng kết nối lại.",
      );
    },
  });

  // Test the active connection.
  const testConnection = useMutation<FacebookChannelTest, Error>({
    mutationFn: () => facebookIntegrationGateway.testConnection(),
  });

  const activeAccounts =
    status?.accounts.filter((a) => a.status === "ACTIVE") ?? [];
  const archivedAccounts =
    status?.accounts.filter((a) => a.status !== "ACTIVE") ?? [];

  const loadManualFlow = (formEvent: FormEvent<HTMLFormElement>) => {
    formEvent.preventDefault();
    const flowId = flowIdDraft.trim();
    if (!flowId) return;
    setSelectedPageId(null);
    setPickerProjectIds([]);
    setError(null);
    setPendingFlowId(flowId);
  };

  const resetPageSelection = () => {
    setPendingFlowId(null);
    setSelectedPageId(null);
    setPickerProjectIds([]);
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

      {/*
        Two different failures share this slot: the OAuth callback's message and
        the activation error. Both report one sentence and ask nothing, so the
        alert carries the sentence as its title and renders no action.
        `[&_p]:whitespace-normal` un-clips the alert's one-line banner
        `md:truncate`, so a long backend message wraps instead of ending in an
        ellipsis.
      */}
      {error ? (
        <div role="alert" className="uu-scope [&_p]:whitespace-normal">
          <AlertFloating
            color="error"
            title={error}
            description=""
            confirmLabel=""
          />
        </div>
      ) : null}

      {/* Meta App credentials (DB-first, env fallback). Required before the
          OAuth flow can build a valid authorization URL. */}
      <form
        className="settings-group settings-messenger-group settings-messenger-credentials"
        autoComplete="off"
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
          {credentialsError ? (
            <div role="alert" className="mb-3 text-body-sm">
              <p>Chưa tải được thông tin ứng dụng Meta.</p>
              <Button
                type="button"
                color="secondary"
                size="sm"
                className="uu-scope mt-2"
                isDisabled={credentialsQuery.isFetching}
                onClick={() => void credentialsQuery.refetch()}
              >
                {credentialsQuery.isFetching
                  ? "Đang tải…"
                  : "Thử lại thông tin ứng dụng"}
              </Button>
            </div>
          ) : null}
          <fieldset
            className="settings-messenger-credentials-grid min-w-0 border-0 p-0"
            disabled={
              saveCredentials.isPending ||
              credentialsPending ||
              credentialsError
            }
            aria-busy={saveCredentials.isPending}
          >
            <legend className="sr-only">Thông tin ứng dụng Meta</legend>
            <PlainField
              id="facebook_app_id"
              label="App ID"
              configured={credentials?.facebook_app_id.configured ?? false}
              statusState={credentialsStatusState}
              value={credentialsForm.facebook_app_id}
              onChange={(value) => onCredentialChange("facebook_app_id", value)}
            />
            <PlainField
              id="facebook_login_config_id"
              label="Configuration ID"
              hint="Không bắt buộc"
              configured={
                credentials?.facebook_login_config_id.configured ?? false
              }
              showMissingStatus={false}
              statusState={credentialsStatusState}
              value={credentialsForm.facebook_login_config_id}
              onChange={(value) =>
                onCredentialChange("facebook_login_config_id", value)
              }
            />
            <SecretField
              id="facebook_app_secret"
              label="App Secret"
              placeholder="Nhập giá trị mới"
              configured={credentials?.facebook_app_secret.configured ?? false}
              statusState={credentialsStatusState}
              preview={credentials?.facebook_app_secret.preview ?? null}
              value={credentialsForm.facebook_app_secret}
              onChange={(value) =>
                onCredentialChange("facebook_app_secret", value)
              }
              reveal={revealAppSecret}
            />
            <SecretField
              id="facebook_webhook_verify_token"
              label="Verify Token"
              placeholder="Nhập giá trị mới"
              hint="Đổi token? Đăng ký lại webhook trên Meta."
              configured={
                credentials?.facebook_webhook_verify_token.configured ?? false
              }
              statusState={credentialsStatusState}
              preview={
                credentials?.facebook_webhook_verify_token.preview ?? null
              }
              value={credentialsForm.facebook_webhook_verify_token}
              onChange={(value) =>
                onCredentialChange("facebook_webhook_verify_token", value)
              }
              reveal={revealVerifyToken}
            />
          </fieldset>
          <div className="settings-oa-actions settings-messenger-actions">
            <Button
              type="submit"
              color="primary"
              className="settings-test-button settings-messenger-solid-action tt-btn-touch"
              isDisabled={
                saveCredentials.isPending ||
                credentialsPending ||
                credentialsError
              }
              aria-busy={saveCredentials.isPending}
            >
              {saveCredentials.isPending
                ? translate("crm.common.saving")
                : translate("crm.common.save_credentials")}
            </Button>
          </div>
        </div>
      </form>

      {/* Connected Pages (multi-Page). One card per ACTIVE Page: status,
          per-Page Project assignment editor (D3), per-Page disconnect.
          Channel test stays group-level — webhook subscription is app-level. */}
      {statusQuery.isError ? (
        <div className="settings-group settings-messenger-group">
          <div
            className="settings-group-content settings-messenger-group-content"
            role="alert"
          >
            <p className="text-body-sm">
              Chưa tải được trạng thái kết nối Messenger.
            </p>
            <Button
              type="button"
              color="secondary"
              size="sm"
              className="uu-scope"
              isDisabled={statusQuery.isFetching}
              onClick={() => void statusQuery.refetch()}
            >
              {statusQuery.isFetching ? "Đang tải…" : "Thử lại trạng thái"}
            </Button>
          </div>
        </div>
      ) : null}
      {!status && statusQuery.isPending ? (
        <div className="settings-group settings-messenger-group">
          <div
            className="settings-group-content settings-messenger-group-content"
            role="status"
          >
            Đang tải trạng thái kết nối…
          </div>
        </div>
      ) : activeAccounts.length > 0 ? (
        <div className="settings-group settings-messenger-group">
          <div className="settings-messenger-group-heading">
            <div>
              <h3 className="settings-messenger-group-title">
                Trang đã kết nối
              </h3>
              <p className="settings-field-hint">
                Mỗi Trang chỉ đề xuất các dự án được gán cho Trang đó.
              </p>
            </div>
            <div className="settings-messenger-heading-actions">
              <Button
                type="button"
                color="secondary"
                className="uu-scope settings-test-button tt-btn-touch"
                onClick={() => testConnection.mutate()}
                isDisabled={testConnection.isPending}
                aria-busy={testConnection.isPending}
              >
                {testConnection.isPending ? "Đang kiểm tra…" : "Kiểm tra kênh"}
              </Button>
              <span
                title={
                  appIdConfigured
                    ? undefined
                    : "Cấu hình App ID trước khi kết nối"
                }
              >
                <Button
                  type="button"
                  color="primary"
                  className="settings-test-button settings-messenger-solid-action tt-btn-touch"
                  onClick={() => startOAuth.mutate()}
                  isDisabled={startOAuth.isPending || !appIdConfigured}
                  aria-busy={startOAuth.isPending}
                >
                  {startOAuth.isPending ? "Đang chuẩn bị…" : "Thêm Trang"}
                </Button>
              </span>
            </div>
          </div>
          <div className="settings-group-content settings-messenger-group-content">
            <ul className="settings-facebook-page-list">
              {activeAccounts.map((account) => (
                <FacebookPageCard
                  key={account.page_id}
                  account={account}
                  projects={activeProjects}
                />
              ))}
            </ul>
            {testConnection.data ? (
              <div role="status" className="uu-scope [&_p]:whitespace-normal">
                <AlertFloating
                  color={testConnection.data.healthy ? "success" : "error"}
                  title={
                    testConnection.data.healthy
                      ? "Kết nối Messenger hoạt động bình thường; webhook đang nhận sự kiện từ các Trang."
                      : (testConnection.data.error ?? "Kết nối không khả dụng.")
                  }
                  description=""
                  confirmLabel=""
                />
              </div>
            ) : null}
          </div>
        </div>
      ) : status ? (
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
            <span
              title={
                appIdConfigured
                  ? undefined
                  : "Cấu hình App ID trước khi kết nối"
              }
            >
              <Button
                type="button"
                color="primary"
                className="settings-test-button settings-messenger-primary-action settings-messenger-solid-action tt-btn-touch"
                onClick={() => startOAuth.mutate()}
                isDisabled={startOAuth.isPending || !appIdConfigured}
                aria-busy={startOAuth.isPending}
              >
                {startOAuth.isPending ? "Đang chuẩn bị…" : "Kết nối Facebook"}
              </Button>
            </span>
          </div>
        </div>
      ) : null}

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
            {/* D1: assign ≥1 Project BEFORE activation — the assignment set is
                committed atomically with activation by complete. An empty
                selection omits project_ids so the backend's 409 detail (not a
                silent no-op) explains the requirement to the operator. */}
            <div className="settings-facebook-page-projects">
              <span className="settings-field-label">
                Gán dự án cho Trang này
              </span>
              {activeProjects.length > 0 ? (
                <FacebookProjectCheckboxList
                  projects={activeProjects}
                  selected={pickerProjectIds}
                  onToggle={(id, checked) =>
                    setPickerProjectIds((current) =>
                      checked
                        ? [...current, id]
                        : current.filter((existing) => existing !== id),
                    )
                  }
                />
              ) : (
                <span className="settings-field-hint">
                  Chưa có dự án nào đang hoạt động — hãy tạo dự án trước khi
                  kích hoạt Trang.
                </span>
              )}
            </div>
            <Button
              type="button"
              color="primary"
              className="settings-test-button settings-messenger-primary-action settings-messenger-solid-action tt-btn-touch"
              onClick={() => {
                if (!selectedPageId) return;
                completeOAuth.mutate({
                  flow_id: pendingFlowId,
                  page_id: selectedPageId,
                  ...(pickerProjectIds.length > 0
                    ? { project_ids: pickerProjectIds }
                    : {}),
                });
              }}
              isDisabled={!selectedPageId || completeOAuth.isPending}
              aria-busy={completeOAuth.isPending}
            >
              {completeOAuth.isPending ? "Đang kích hoạt…" : "Kích hoạt Trang"}
            </Button>
          </div>
        </div>
      ) : null}

      {needsPageListRecovery ? (
        <div role="alert" className="uu-scope [&_p]:whitespace-normal">
          <AlertFloating
            color="error"
            title={
              isPageListError
                ? "Không thể tải danh sách Trang. Mã phiên có thể không hợp lệ hoặc đã hết hạn."
                : "Không tìm thấy Trang Facebook nào trong phiên kết nối này."
            }
            description="Vui lòng kết nối lại hoặc nhập một mã phiên khác."
            confirmLabel="Quay lại kết nối"
            onConfirm={resetPageSelection}
          />
        </div>
      ) : null}

      {/* Manual flow-id entry (after OAuth redirect back to frontend).
          Available even with Pages connected — a lost flow id must remain
          recoverable in the multi-Page add-Page flow. */}
      {!pendingFlowId ? (
        <details className="settings-group settings-messenger-recovery">
          <summary className="settings-messenger-recovery-summary">
            Nhập mã phiên OAuth
          </summary>
          <div className="settings-messenger-recovery-content">
            <form
              className="settings-field settings-messenger-recovery-form"
              autoComplete="off"
              onSubmit={loadManualFlow}
            >
              <label
                className="settings-field-label"
                htmlFor="facebook-oauth-flow-id"
              >
                Mã phiên OAuth
              </label>
              <InputBase
                size="sm"
                id="facebook-oauth-flow-id"
                name="facebook-oauth-flow-id"
                type="text"
                autoComplete="off"
                spellCheck={false}
                value={flowIdDraft}
                wrapperClassName="settings-input uu-scope h-(--settings-control-height)"
                onChange={(event) => setFlowIdDraft(event.target.value)}
              />
              <span className="settings-field-hint">
                Dùng để tải các Trang đã ủy quyền.
              </span>
              <Button
                type="submit"
                color="primary"
                className="settings-test-button settings-messenger-solid-action tt-btn-touch"
                isDisabled={!flowIdDraft.trim()}
              >
                Tải danh sách Trang
              </Button>
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
