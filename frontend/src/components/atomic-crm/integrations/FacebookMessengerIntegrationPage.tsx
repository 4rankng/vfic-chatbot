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

// ─── Component ─────────────────────────────────────────────────────────────

export const FacebookMessengerIntegrationPage = () => {
  const queryClient = useQueryClient();
  const [pendingFlowId, setPendingFlowId] = useState<string | null>(null);
  const [flowIdDraft, setFlowIdDraft] = useState("");
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    <section className="settings-section-panel">
      <h2 className="settings-card-title">Facebook Messenger</h2>
      <p className="settings-card-description">
        Kết nối một Trang Facebook để nhận và trả lời tin nhắn ứng viên qua
        Messenger. V1 hỗ trợ tối đa một Trang đang hoạt động.
      </p>

      {error ? (
        <div
          className="settings-test-result settings-test-result-error"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      {/* Active connection */}
      {activeAccount ? (
        <div className="settings-card">
          <div className="settings-field">
            <span className="settings-field-label">Trang đang kết nối</span>
            <span className="settings-field-value">
              <strong>{activeAccount.label}</strong>{" "}
              <span className="settings-field-hint">
                (…{activeAccount.page_id_suffix})
              </span>
            </span>
          </div>
          <div className="settings-oa-actions">
            <button
              type="button"
              className="settings-test-button"
              onClick={() => testConnection.mutate()}
              disabled={testConnection.isPending}
            >
              {testConnection.isPending ? "Đang kiểm tra…" : "Kiểm tra kết nối"}
            </button>
            <button
              type="button"
              className="settings-test-button"
              onClick={() => disconnect.mutate()}
              disabled={disconnect.isPending}
            >
              {disconnect.isPending ? "Đang ngắt…" : "Ngắt kết nối"}
            </button>
          </div>
          {testConnection.data ? (
            <div
              className={`settings-test-result ${
                testConnection.data.healthy
                  ? "settings-test-result-ok"
                  : "settings-test-result-error"
              }`}
            >
              {testConnection.data.healthy
                ? "Kết nối Messenger hoạt động bình thường."
                : (testConnection.data.error ?? "Kết nối không khả dụng.")}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="settings-card">
          <p className="settings-field-hint">
            Chưa có Trang Facebook nào được kết nối.
          </p>
          <button
            type="button"
            className="settings-test-button"
            onClick={() => startOAuth.mutate()}
            disabled={startOAuth.isPending}
          >
            {startOAuth.isPending ? "Đang chuẩn bị…" : "Kết nối Facebook"}
          </button>
        </div>
      )}

      {/* Page selection after OAuth callback */}
      {pendingFlowId && pageList?.pages && pageList.pages.length > 0 ? (
        <div className="settings-card">
          <h3 className="settings-card-title">Chọn Trang để kích hoạt</h3>
          <ul className="settings-page-list">
            {pageList.pages.map((page) => (
              <li key={page.id}>
                <label>
                  <input
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
            className="settings-test-button"
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
      ) : null}

      {needsPageListRecovery ? (
        <div
          className="settings-test-result settings-test-result-error"
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
            className="settings-test-button"
            onClick={resetPageSelection}
          >
            Quay lại kết nối
          </button>
        </div>
      ) : null}

      {/* Manual flow-id entry (after OAuth redirect back to frontend) */}
      {!activeAccount && !pendingFlowId ? (
        <div className="settings-card">
          <details>
            <summary className="settings-field-hint">
              Đã hoàn tất ủy quyền? Nhập mã phiên để tiếp tục.
            </summary>
            <form className="settings-field" onSubmit={loadManualFlow}>
              <label
                className="settings-field-label"
                htmlFor="facebook-oauth-flow-id"
              >
                Mã phiên OAuth
              </label>
              <input
                id="facebook-oauth-flow-id"
                name="facebook-oauth-flow-id"
                type="text"
                autoComplete="off"
                spellCheck={false}
                value={flowIdDraft}
                onChange={(event) => setFlowIdDraft(event.target.value)}
              />
              <span className="settings-field-hint">
                Mã phiên chỉ dùng để tải các Trang đã được Facebook ủy quyền.
              </span>
              <button
                type="submit"
                className="settings-test-button"
                disabled={!flowIdDraft.trim()}
              >
                Tải danh sách Trang
              </button>
            </form>
          </details>
        </div>
      ) : null}

      {/* Archived Page scopes (read-only history) */}
      {archivedAccounts.length > 0 ? (
        <div className="settings-card">
          <h3 className="settings-card-title">Trang đã ngắt kết nối</h3>
          <p className="settings-field-hint">
            Lịch sử hội thoại được giữ lại (chỉ xem). Kết nối lại cùng Trang để
            tiếp tục trả lời.
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
      ) : null}
    </section>
  );
};
