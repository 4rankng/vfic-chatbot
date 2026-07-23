import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

type ApiOptions = {
  method?: string;
  body?: unknown;
};

const mocks = vi.hoisted(() => ({
  accounts: [] as Array<{
    page_id_suffix: string;
    label: string;
    status: "ACTIVE" | "INACTIVE";
  }>,
  pageListResult: {
    pages: [{ id: "page-123456789", name: "Ting Ting Tuyển dụng" }],
    active_page_id: null,
  } as
    | {
        pages: Array<{ id: string; name: string }>;
        active_page_id: string | null;
      }
    | Error,
  completeResult: {
    page_id_suffix: "6789",
    label: "Ting Ting Tuyển dụng",
    status: "ACTIVE" as const,
  } as
    | {
        page_id_suffix: string;
        label: string;
        status: "ACTIVE" | "INACTIVE";
      }
    | Error,
  loadStatus: vi.fn(() =>
    Promise.resolve({ enabled: true, accounts: mocks.accounts }),
  ),
  loadCredentials: vi.fn(() =>
    Promise.resolve({
      facebook_app_id: { configured: false, value: null },
      facebook_app_secret: { configured: false, preview: null },
      facebook_login_config_id: { configured: false, value: null },
      facebook_webhook_verify_token: {
        configured: false,
        preview: null,
      },
    }),
  ),
  saveCredentials: vi.fn(),
  loadOAuthPages: vi.fn((_flowId: string) =>
    mocks.pageListResult instanceof Error
      ? Promise.reject(mocks.pageListResult)
      : Promise.resolve(mocks.pageListResult),
  ),
  startOAuth: vi.fn(),
  completeOAuth: vi.fn((_body: ApiOptions["body"]) =>
    mocks.completeResult instanceof Error
      ? Promise.reject(mocks.completeResult)
      : Promise.resolve(mocks.completeResult),
  ),
  testConnection: vi.fn(),
  disconnect: vi.fn(() =>
    Promise.resolve({
      page_id_suffix: "4321",
      label: "Ting Ting Tuyển dụng",
      status: "INACTIVE",
    }),
  ),
}));

vi.mock("./api", () => ({
  facebookIntegrationGateway: {
    loadStatus: mocks.loadStatus,
    loadCredentials: mocks.loadCredentials,
    saveCredentials: mocks.saveCredentials,
    loadOAuthPages: mocks.loadOAuthPages,
    startOAuth: mocks.startOAuth,
    completeOAuth: mocks.completeOAuth,
    testConnection: mocks.testConnection,
    disconnect: mocks.disconnect,
  },
}));

import { FacebookMessengerIntegrationPage } from "./FacebookMessengerIntegrationPage";

const renderPage = async () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <FacebookMessengerIntegrationPage />
    </QueryClientProvider>,
  );
};

afterEach(async () => {
  await cleanup();
  mocks.accounts = [];
  mocks.pageListResult = {
    pages: [{ id: "page-123456789", name: "Ting Ting Tuyển dụng" }],
    active_page_id: null,
  };
  mocks.completeResult = {
    page_id_suffix: "6789",
    label: "Ting Ting Tuyển dụng",
    status: "ACTIVE",
  };
  mocks.loadStatus.mockClear();
  mocks.loadCredentials.mockClear();
  mocks.saveCredentials.mockClear();
  mocks.loadOAuthPages.mockClear();
  mocks.startOAuth.mockClear();
  mocks.completeOAuth.mockClear();
  mocks.testConnection.mockClear();
  mocks.disconnect.mockClear();
  window.history.replaceState(null, "", "/#/settings");
});

describe("FacebookMessengerIntegrationPage", () => {
  it("shows compact status icons for every credential and a group summary", async () => {
    const screen = await renderPage();
    const statuses = screen.container.querySelectorAll(
      ".settings-messenger-credentials-grid .settings-field-status",
    );

    expect(statuses).toHaveLength(4);
    statuses.forEach((status) => {
      expect(status.getAttribute("aria-label")).toBe("Chưa cấu hình");
      expect(status.textContent).toBe("");
    });
    expect(
      screen.container.querySelector(".settings-group-status")?.getAttribute(
        "aria-label",
      ),
    ).toBe("0/4 trường đã cấu hình");
  });

  it("keeps the empty state and recovery form inside flat settings groups", async () => {
    const screen = await renderPage();

    const emptyTitle = screen.getByText("Chưa kết nối");
    await expect.element(emptyTitle).toBeVisible();

    const emptyContent = emptyTitle
      .element()
      .closest(".settings-group-content");
    expect(emptyContent).not.toBeNull();
    expect(
      screen
        .getByRole("button", { name: "Kết nối Facebook" })
        .element()
        .closest(".settings-group-content"),
    ).toBe(emptyContent);

    const recoverySummary = screen.getByText("Nhập mã phiên OAuth");
    const recoveryGroup = recoverySummary.element().closest("details");
    expect(recoveryGroup).not.toBeNull();
    expect(recoveryGroup?.classList.contains("settings-group")).toBe(true);
    expect(
      recoveryGroup?.querySelector(".settings-messenger-recovery-content"),
    ).not.toBeNull();
  });

  it("keeps enabled and disabled primary actions readable", async () => {
    const screen = await renderPage();
    const saveButton = screen.getByRole("button", { name: "Lưu thông tin" });
    const connectButton = screen.getByRole("button", {
      name: "Kết nối Facebook",
    });

    await expect.element(saveButton).toBeVisible();
    await expect.element(connectButton).toBeDisabled();

    const saveStyle = getComputedStyle(saveButton.element());
    const disabledStyle = getComputedStyle(connectButton.element());
    expect(saveStyle.color).not.toBe(saveStyle.backgroundColor);
    expect(disabledStyle.color).not.toBe(disabledStyle.backgroundColor);
    expect(disabledStyle.opacity).toBe("1");
    expect(disabledStyle.cursor).toBe("not-allowed");
  });

  it("consumes the OAuth callback flow ID, cleans the URL, and completes Page selection", async () => {
    window.history.replaceState(
      null,
      "",
      "/#/settings?section=channels&facebook_oauth_status=pending_selection&facebook_oauth_flow_id=opaque-flow-123",
    );

    const screen = await renderPage();

    const pageRadio = screen.getByRole("radio", {
      name: "Ting Ting Tuyển dụng",
    });
    await expect.element(pageRadio).toBeVisible();
    expect(window.location.hash).toBe("#/settings?section=channels");
    expect(window.location.href).not.toContain("opaque-flow-123");

    await pageRadio.click();
    await screen.getByRole("button", { name: "Kích hoạt Trang" }).click();

    await expect
      .poll(() =>
        mocks.completeOAuth.mock.calls.some(
          ([body]) =>
            JSON.stringify(body) ===
            JSON.stringify({
              flow_id: "opaque-flow-123",
              page_id: "page-123456789",
            }),
        ),
      )
      .toBe(true);
  });

  it("keeps the manual flow ID field visible while typing and commits the trimmed full value", async () => {
    const screen = await renderPage();
    await screen.getByText("Nhập mã phiên OAuth").click();
    const input = screen.getByRole("textbox", { name: "Mã phiên OAuth" });

    await input.fill("  opaque-manual-flow-id  ");
    await expect.element(input).toBeVisible();
    await expect.element(input).toHaveValue("  opaque-manual-flow-id  ");

    expect(mocks.loadOAuthPages).not.toHaveBeenCalled();
    await screen.getByRole("button", { name: "Tải danh sách Trang" }).click();

    await expect
      .poll(() =>
        mocks.loadOAuthPages.mock.calls.some(
          ([flowId]) => flowId === "opaque-manual-flow-id",
        ),
      )
      .toBe(true);
  });

  it("returns to a fresh connection flow when Page activation fails", async () => {
    mocks.completeResult = new Error("HTTP 410: OAuth flow already consumed");
    window.history.replaceState(
      null,
      "",
      "/#/settings?facebook_oauth_status=pending_selection&facebook_oauth_flow_id=consumed-flow",
    );
    const screen = await renderPage();
    const pageRadio = screen.getByRole("radio", {
      name: "Ting Ting Tuyển dụng",
    });
    await expect.element(pageRadio).toBeVisible();

    await pageRadio.click();
    await screen.getByRole("button", { name: "Kích hoạt Trang" }).click();

    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent("Kích hoạt Trang thất bại. Vui lòng kết nối lại.");
    expect(pageRadio.query()).toBeNull();
    await expect
      .element(screen.getByRole("button", { name: "Kết nối Facebook" }))
      .toBeVisible();
    await expect.element(screen.getByText("Nhập mã phiên OAuth")).toBeVisible();
  });

  it("disconnects the single active Page without sending its masked suffix", async () => {
    mocks.accounts = [
      {
        page_id_suffix: "4321",
        label: "Ting Ting Tuyển dụng",
        status: "ACTIVE",
      },
    ];
    const screen = await renderPage();

    await screen.getByRole("button", { name: "Ngắt kết nối" }).click();

    await expect.poll(() => mocks.disconnect.mock.calls.length).toBe(1);
    expect(mocks.disconnect.mock.calls.every((call) => call.length === 0)).toBe(
      true,
    );
  });

  it("shows safe generic Vietnamese copy for an unknown OAuth callback error", async () => {
    window.history.replaceState(
      null,
      "",
      "/#/settings?facebook_oauth_status=error&facebook_oauth_error=provider_message_with_details",
    );

    const screen = await renderPage();

    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent(
        "Không thể hoàn tất kết nối Facebook. Vui lòng thử lại.",
      );
    expect(screen.container.textContent).not.toContain(
      "provider_message_with_details",
    );
    expect(window.location.hash).toBe("#/settings");
  });

  it("recovers from a rejected Page query without stranding the connection flow", async () => {
    mocks.pageListResult = new Error("HTTP 410: OAuth flow expired");
    window.history.replaceState(
      null,
      "",
      "/#/settings?facebook_oauth_status=pending_selection&facebook_oauth_flow_id=expired-flow",
    );

    const screen = await renderPage();

    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent(
        "Không thể tải danh sách Trang. Mã phiên có thể không hợp lệ hoặc đã hết hạn.",
      );
    await screen.getByRole("button", { name: "Quay lại kết nối" }).click();

    await expect.element(screen.getByText("Nhập mã phiên OAuth")).toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Kết nối Facebook" }))
      .toBeVisible();
    expect(screen.getByRole("alert").query()).toBeNull();
  });

  it("offers the same recovery when an OAuth flow has no available Pages", async () => {
    mocks.pageListResult = { pages: [], active_page_id: null };
    window.history.replaceState(
      null,
      "",
      "/#/settings?facebook_oauth_status=pending_selection&facebook_oauth_flow_id=empty-flow",
    );

    const screen = await renderPage();

    await expect
      .element(screen.getByRole("alert"))
      .toHaveTextContent(
        "Không tìm thấy Trang Facebook nào trong phiên kết nối này.",
      );
    await screen.getByRole("button", { name: "Quay lại kết nối" }).click();

    await expect.element(screen.getByText("Nhập mã phiên OAuth")).toBeVisible();
    expect(screen.getByRole("alert").query()).toBeNull();
  });
});
