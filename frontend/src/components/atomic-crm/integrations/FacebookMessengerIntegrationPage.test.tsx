import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/apiClient";

type ApiOptions = {
  method?: string;
  body?: unknown;
};

const mocks = vi.hoisted(() => ({
  accounts: [] as Array<{
    page_id: string;
    page_id_suffix: string;
    label: string;
    status: "ACTIVE" | "INACTIVE";
  }>,
  projects: [] as Array<{ id: string; name: string; is_active: boolean }>,
  notify: vi.fn(),
  pageListResult: {
    pages: [{ id: "page-123456789", name: "Ting Ting Tuyển dụng" }],
    active_page_ids: [] as string[],
  } as
    | {
        pages: Array<{ id: string; name: string }>;
        active_page_ids: string[];
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
      facebook_app_id: { configured: false, value: null as string | null },
      facebook_app_secret: { configured: false, preview: null },
      facebook_login_config_id: {
        configured: false,
        value: null as string | null,
      },
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
  startOAuth: vi.fn(() =>
    Promise.resolve({
      authorization_url:
        "https://www.facebook.com/v21.0/dialog/oauth?client_id=test",
    }),
  ),
  completeOAuth: vi.fn((_body: ApiOptions["body"]) =>
    mocks.completeResult instanceof Error
      ? Promise.reject(mocks.completeResult)
      : Promise.resolve(mocks.completeResult),
  ),
  testConnection: vi.fn(() =>
    Promise.resolve({ healthy: true, error: null, app_subscribed: true }),
  ),
  disconnectPage: vi.fn(() =>
    Promise.resolve({
      page_id_suffix: "1111",
      label: "Tuyển dụng chính thức Việt Pháp",
      status: "INACTIVE" as const,
    }),
  ),
  setPageProjects: vi.fn((_pageId: string, projectIds: string[]) =>
    Promise.resolve({
      page_id: _pageId,
      assignments: projectIds.map((project_id) => ({ project_id })),
    }),
  ),
  loadPageProjects: vi.fn((pageId: string) =>
    Promise.resolve({
      page_id: pageId,
      assignments:
        pageId === "222222222222222"
          ? [{ project_id: "3" }]
          : [{ project_id: "1" }, { project_id: "2" }],
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
    disconnectPage: mocks.disconnectPage,
    setPageProjects: mocks.setPageProjects,
    loadPageProjects: mocks.loadPageProjects,
  },
}));

// The multi-Page editor lists active Projects via useGetList; this harness has
// no DataProvider context, so the options are provided inline.
vi.mock("ra-core", () => ({
  // The component under test reads its labels from the Vietnamese catalog.
  useTranslate: () => testI18nProvider.translate,
  useGetList: () => ({ data: mocks.projects }),
  useNotify: () => mocks.notify,
}));

import { FacebookMessengerIntegrationPage } from "./FacebookMessengerIntegrationPage";
import { testI18nProvider } from "@/components/atomic-crm/providers/commons/i18nProvider";

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

const CONNECTED_ACCOUNTS = [
  {
    page_id: "111111111111111",
    page_id_suffix: "1111",
    label: "Tuyển dụng chính thức Việt Pháp",
    status: "ACTIVE" as const,
  },
  {
    page_id: "222222222222222",
    page_id_suffix: "2222",
    label: "Tuyển dụng thực tập sinh",
    status: "ACTIVE" as const,
  },
];

const MOCK_PROJECTS = [
  { id: "1", name: "LG Display — Tuyển dụng chính thức", is_active: true },
  { id: "2", name: "LG Display — Thực tập sinh", is_active: true },
  { id: "3", name: "VFIC Express", is_active: true },
];

afterEach(async () => {
  await cleanup();
  mocks.accounts = [];
  mocks.projects = [];
  mocks.notify.mockClear();
  mocks.pageListResult = {
    pages: [{ id: "page-123456789", name: "Ting Ting Tuyển dụng" }],
    active_page_ids: [],
  };
  mocks.completeResult = {
    page_id_suffix: "6789",
    label: "Ting Ting Tuyển dụng",
    status: "ACTIVE",
  };
  mocks.loadStatus.mockClear();
  mocks.loadCredentials.mockClear();
  mocks.saveCredentials.mockClear();
  mocks.setPageProjects.mockClear();
  mocks.loadPageProjects.mockClear();
  mocks.loadOAuthPages.mockClear();
  mocks.startOAuth.mockClear();
  mocks.completeOAuth.mockClear();
  mocks.testConnection.mockClear();
  mocks.disconnectPage.mockClear();
  window.history.replaceState(null, "", "/#/settings");
});

describe("FacebookMessengerIntegrationPage", () => {
  it("marks application credentials to avoid reusing saved login credentials", async () => {
    const screen = await renderPage();
    const appId = screen.getByRole("textbox", { name: /^App ID/ });
    const secret = screen.getByRole("textbox", { name: /^App Secret/ });
    await expect.element(appId).toBeVisible();
    await expect.element(appId).toHaveAttribute("name", "facebook_app_id");
    await expect.element(appId).toHaveAttribute("autocomplete", "off");
    await expect.element(secret).toHaveAttribute("name", "facebook_app_secret");
    await expect
      .element(secret)
      .toHaveAttribute("autocomplete", "new-password");
    expect(appId.element().closest("form")?.getAttribute("autocomplete")).toBe(
      "off",
    );
    await expect.element(secret).toHaveValue("");
  });

  it("offers retry instead of reporting disconnected when Page status cannot load", async () => {
    mocks.loadStatus.mockRejectedValueOnce(new Error("Unavailable"));
    const screen = await renderPage();
    await expect
      .element(screen.getByText("Chưa tải được trạng thái kết nối Messenger."))
      .toBeVisible();
    expect(screen.container.textContent).not.toContain("Chưa kết nối");
    await screen.getByRole("button", { name: "Thử lại trạng thái" }).click();
    await expect
      .element(screen.getByText("Chưa kết nối", { exact: true }))
      .toBeVisible();
  });

  it("locks credential inputs while saving so a new edit cannot be discarded", async () => {
    let finish!: (value: unknown) => void;
    mocks.saveCredentials.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const screen = await renderPage();
    await screen.getByRole("textbox", { name: /^App ID/ }).fill("new-app-id");
    await screen.getByRole("button", { name: "Lưu thông tin" }).click();
    await expect
      .element(screen.getByRole("textbox", { name: /^App ID/ }))
      .toBeDisabled();
    finish({
      facebook_app_id: { configured: true, value: "new-app-id" },
      facebook_app_secret: { configured: false, preview: null },
      facebook_login_config_id: { configured: false, value: null },
      facebook_webhook_verify_token: { configured: false, preview: null },
    });
    await expect
      .element(screen.getByRole("textbox", { name: /^App ID/ }))
      .toBeEnabled();
  });

  it("keeps failed Page assignments private until a successful retry", async () => {
    mocks.accounts = [CONNECTED_ACCOUNTS[0]];
    mocks.projects = MOCK_PROJECTS;
    mocks.loadPageProjects.mockRejectedValueOnce(new Error("Unavailable"));
    const screen = await renderPage();
    await expect
      .element(screen.getByText("Chưa tải được dự án đã gán cho Trang."))
      .toBeVisible();
    expect(screen.getByRole("checkbox").all()).toHaveLength(0);
    expect(screen.container.textContent).not.toContain(
      "Trang chưa gán dự án nào",
    );
    await screen.getByRole("button", { name: "Thử lại" }).click();
    await expect
      .element(screen.getByRole("checkbox", { name: MOCK_PROJECTS[0].name }))
      .toBeChecked();
    expect(mocks.setPageProjects).not.toHaveBeenCalled();
  });

  it("locks Page assignment controls while their replacement is saving", async () => {
    mocks.accounts = [CONNECTED_ACCOUNTS[0]];
    mocks.projects = MOCK_PROJECTS;
    let finish!: (value: object) => void;
    mocks.setPageProjects.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }) as never,
    );
    const screen = await renderPage();
    const selected = screen.getByRole("checkbox", {
      name: MOCK_PROJECTS[0].name,
    });
    await expect.element(selected).toBeChecked();
    // React Aria's checkbox input is visually hidden; the visible label owns
    // pointer interaction while the input retains keyboard/checked semantics.
    await screen.getByText(MOCK_PROJECTS[0].name, { exact: true }).click();
    await screen.getByRole("button", { name: "Lưu dự án" }).click();
    await expect.poll(() => mocks.setPageProjects.mock.calls.length).toBe(1);
    await expect.element(selected).toBeDisabled();
    finish({
      page_id: CONNECTED_ACCOUNTS[0].page_id,
      assignments: [{ project_id: "2" }],
    });
    await expect.element(selected).not.toBeDisabled();
  });

  it("shows compact status icons for every credential and a group summary", async () => {
    const screen = await renderPage();
    await expect
      .poll(
        () =>
          screen.container.querySelector(".settings-group-status .sr-only")
            ?.textContent,
      )
      .toBe("0/3 trường đã cấu hình");

    const statuses = screen.container.querySelectorAll(
      ".settings-messenger-credentials-grid .settings-field-status",
    );

    expect(statuses).toHaveLength(3);
    statuses.forEach((status) => {
      expect(status.getAttribute("aria-label")).toBe("Chưa cấu hình");
      expect(status.textContent).toBe("");
    });
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

  it("surfaces the backend reason when activation fails with a friendly detail", async () => {
    mocks.completeResult = new ApiError(
      409,
      "Trang cần ít nhất một dự án được gán trước khi kích hoạt.",
    );
    window.history.replaceState(
      null,
      "",
      "/#/settings?facebook_oauth_status=pending_selection&facebook_oauth_flow_id=gated-flow",
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
      .toHaveTextContent(
        "Trang cần ít nhất một dự án được gán trước khi kích hoạt.",
      );
    expect(pageRadio.query()).toBeNull();
  });

  it("renders one card per active Page with status badge and Project editor", async () => {
    mocks.accounts = CONNECTED_ACCOUNTS;
    mocks.projects = MOCK_PROJECTS;
    const screen = await renderPage();

    await expect.element(screen.getByText("Trang đã kết nối")).toBeVisible();
    await expect
      .element(screen.getByText("Tuyển dụng chính thức Việt Pháp"))
      .toBeVisible();
    await expect
      .element(screen.getByText("Tuyển dụng thực tập sinh"))
      .toBeVisible();

    // One status badge per connected Page, both reading "Đang hoạt động".
    const pageStatuses = screen.getByText("Đang hoạt động").all();
    expect(pageStatuses).toHaveLength(2);

    // One checkbox per Page × Project option: 2 cards × 3 Project options.
    const checkboxes = screen.getByRole("checkbox").all();
    expect(checkboxes).toHaveLength(6);
  });

  it("saves per-Page Project assignment from the card editor", async () => {
    mocks.accounts = CONNECTED_ACCOUNTS;
    mocks.projects = MOCK_PROJECTS;
    const screen = await renderPage();

    // Wait for the connected-Pages group to render before counting cards.
    await expect.element(screen.getByText("Trang đã kết nối")).toBeVisible();

    const cards = screen.container.querySelectorAll(
      ".settings-facebook-page-item",
    );
    expect(cards).toHaveLength(2);

    const saveButtons = screen.container.querySelectorAll(
      ".settings-facebook-project-save",
    );
    expect(saveButtons).toHaveLength(2);
    expect((saveButtons[0] as HTMLButtonElement).disabled).toBe(true);

    // Toggle "VFIC Express" ON for card 1 (server had ["1","2"]). The option is
    // a Untitled UI checkbox: the control is visually hidden and the wrapping
    // label is the click target, so the test clicks the option name.
    await screen.getByText("VFIC Express").first().click();

    expect((saveButtons[0] as HTMLButtonElement).disabled).toBe(false);
    await expect
      .element(screen.getByRole("button", { name: "Lưu dự án" }).first())
      .toBeEnabled();

    // Commit card 1's assignment.
    await screen.getByRole("button", { name: "Lưu dự án" }).first().click();

    await expect.poll(() => mocks.setPageProjects.mock.calls.length).toBe(1);
    expect(mocks.setPageProjects.mock.calls[0]).toEqual([
      "111111111111111",
      ["1", "2", "3"],
    ]);
  });

  it("offers Thêm Trang without disrupting existing Pages", async () => {
    mocks.accounts = CONNECTED_ACCOUNTS;
    mocks.projects = MOCK_PROJECTS;
    // "Thêm Trang" requires a configured App ID, same as the empty-state
    // "Kết nối Facebook" action.
    mocks.loadCredentials.mockResolvedValueOnce({
      facebook_app_id: { configured: true, value: "app-id" },
      facebook_app_secret: { configured: false, preview: null },
      facebook_login_config_id: { configured: false, value: null },
      facebook_webhook_verify_token: { configured: false, preview: null },
    });
    const screen = await renderPage();

    await expect
      .element(screen.getByRole("button", { name: "Thêm Trang" }))
      .toBeVisible();
    await expect
      .element(screen.getByText("Tuyển dụng chính thức Việt Pháp"))
      .toBeVisible();

    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    await screen.getByRole("button", { name: "Thêm Trang" }).click();

    await expect.poll(() => mocks.startOAuth.mock.calls.length).toBe(1);
    await expect.poll(() => openSpy.mock.calls.length).toBe(1);
    expect(openSpy.mock.calls[0]?.[0]).toBe(
      "https://www.facebook.com/v21.0/dialog/oauth?client_id=test",
    );
    // Existing Pages remain listed while the add-Page flow is in flight.
    await expect
      .element(screen.getByText("Tuyển dụng chính thức Việt Pháp"))
      .toBeVisible();
    openSpy.mockRestore();
  });

  it("commits the picker's Project assignment atomically with activation", async () => {
    mocks.projects = MOCK_PROJECTS;
    window.history.replaceState(
      null,
      "",
      "/#/settings?facebook_oauth_status=pending_selection&facebook_oauth_flow_id=picker-flow",
    );
    const screen = await renderPage();

    const pageRadio = screen.getByRole("radio", {
      name: "Ting Ting Tuyển dụng",
    });
    await expect.element(pageRadio).toBeVisible();
    await pageRadio.click();

    // Same as the card editor: the option name is the click target.
    await screen
      .getByText("LG Display — Tuyển dụng chính thức")
      .first()
      .click();

    await screen.getByRole("button", { name: "Kích hoạt Trang" }).click();

    await expect
      .poll(() =>
        mocks.completeOAuth.mock.calls.some(
          ([body]) =>
            JSON.stringify(body) ===
            JSON.stringify({
              flow_id: "picker-flow",
              page_id: "page-123456789",
              project_ids: ["1"],
            }),
        ),
      )
      .toBe(true);
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
    mocks.pageListResult = { pages: [], active_page_ids: [] };
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

  it("disconnects one Page by full id from its card without touching the others", async () => {
    mocks.accounts = CONNECTED_ACCOUNTS;
    mocks.projects = MOCK_PROJECTS;
    const screen = await renderPage();

    await expect.element(screen.getByText("Trang đã kết nối")).toBeVisible();

    await screen.getByRole("button", { name: "Ngắt kết nối" }).last().click();

    await expect.poll(() => mocks.disconnectPage.mock.calls.length).toBe(1);
    expect(mocks.disconnectPage.mock.calls[0]).toEqual(["222222222222222"]);
    await expect
      .element(screen.getByText("Tuyển dụng chính thức Việt Pháp"))
      .toBeVisible();
  });
});
