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
  apiJson: vi.fn((path: string, options?: ApiOptions): Promise<unknown> => {
    if (path === "/api/v1/admin/integrations/facebook") {
      if (options?.method === "DELETE") {
        return Promise.resolve({
          page_id_suffix: "4321",
          label: "Ting Ting Tuyển dụng",
          status: "INACTIVE",
        });
      }
      return Promise.resolve({ enabled: true, accounts: mocks.accounts });
    }
    if (path.startsWith("/api/v1/admin/integrations/facebook/oauth/pages?")) {
      return mocks.pageListResult instanceof Error
        ? Promise.reject(mocks.pageListResult)
        : Promise.resolve(mocks.pageListResult);
    }
    if (path === "/api/v1/admin/integrations/facebook/oauth/complete") {
      return mocks.completeResult instanceof Error
        ? Promise.reject(mocks.completeResult)
        : Promise.resolve(mocks.completeResult);
    }
    return Promise.reject(new Error(`Unexpected API path: ${path}`));
  }),
}));

vi.mock("../providers/rest/api", () => ({ apiJson: mocks.apiJson }));

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
  mocks.apiJson.mockClear();
  window.history.replaceState(null, "", "/#/settings");
});

describe("FacebookMessengerIntegrationPage", () => {
  it("keeps the empty state and recovery form inside their card content shells", async () => {
    const screen = await renderPage();

    const emptyTitle = screen.getByText("Chưa kết nối Trang Facebook");
    await expect.element(emptyTitle).toBeVisible();

    const emptyContent = emptyTitle.element().closest(".settings-card-content");
    expect(emptyContent).not.toBeNull();
    expect(
      screen
        .getByRole("button", { name: "Kết nối Facebook" })
        .element()
        .closest(".settings-card-content"),
    ).toBe(emptyContent);

    const recoverySummary = screen.getByText(
      "Đã có mã phiên? Nhập mã để tiếp tục",
    );
    const recoveryCard = recoverySummary.element().closest("details");
    expect(recoveryCard).not.toBeNull();
    expect(recoveryCard?.classList.contains("settings-card")).toBe(true);
    expect(
      recoveryCard?.querySelector(".settings-messenger-recovery-content"),
    ).not.toBeNull();
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
        mocks.apiJson.mock.calls.some(
          ([path, options]) =>
            path === "/api/v1/admin/integrations/facebook/oauth/complete" &&
            options?.method === "POST" &&
            JSON.stringify(options.body) ===
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
    await screen.getByText("Đã có mã phiên? Nhập mã để tiếp tục").click();
    const input = screen.getByRole("textbox", { name: "Mã phiên OAuth" });

    await input.fill("  opaque-manual-flow-id  ");
    await expect.element(input).toBeVisible();
    await expect.element(input).toHaveValue("  opaque-manual-flow-id  ");

    expect(
      mocks.apiJson.mock.calls.some(([path]) => path.includes("oauth/pages")),
    ).toBe(false);
    await screen.getByRole("button", { name: "Tải danh sách Trang" }).click();

    await expect
      .poll(() =>
        mocks.apiJson.mock.calls.some(
          ([path]) =>
            path ===
            "/api/v1/admin/integrations/facebook/oauth/pages?flow_id=opaque-manual-flow-id",
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
    await expect
      .element(screen.getByText("Đã có mã phiên? Nhập mã để tiếp tục"))
      .toBeVisible();
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

    await expect
      .poll(() =>
        mocks.apiJson.mock.calls.some(
          ([path, options]) =>
            path === "/api/v1/admin/integrations/facebook" &&
            options?.method === "DELETE",
        ),
      )
      .toBe(true);
    expect(
      mocks.apiJson.mock.calls.some(([path]) => path.includes("page_id=")),
    ).toBe(false);
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

    await expect
      .element(screen.getByText("Đã có mã phiên? Nhập mã để tiếp tục"))
      .toBeVisible();
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

    await expect
      .element(screen.getByText("Đã có mã phiên? Nhập mã để tiếp tục"))
      .toBeVisible();
    expect(screen.getByRole("alert").query()).toBeNull();
  });
});
