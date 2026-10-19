import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  loadOdsSettings: vi.fn(),
  saveOdsSettings: vi.fn(),
  testOdsConnection: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
}));

vi.mock("./api", () => ({
  zaloIntegrationGateway: {
    loadOdsSettings: mocks.loadOdsSettings,
    saveOdsSettings: mocks.saveOdsSettings,
    testOdsConnection: mocks.testOdsConnection,
  },
}));

import { OdsSection } from "./OdsSection";

const STORED_SETTINGS = {
  service_name: "CloudFone",
  auth_user: "ods-user",
  auth_key: { configured: true, preview: "9 ký tự" },
  recipients: ["quanly@vp.vn"],
  enabled: true,
};

const renderSection = async () => {
  const screen = render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <OdsSection />
    </QueryClientProvider>,
  );
  return screen;
};

afterEach(async () => {
  await cleanup();
  mocks.loadOdsSettings.mockReset();
  mocks.saveOdsSettings.mockReset();
  mocks.testOdsConnection.mockReset();
  mocks.notify.mockClear();
});

describe("OdsSection", () => {
  it("renders the stored configuration and the daily status line", async () => {
    mocks.loadOdsSettings.mockResolvedValue(STORED_SETTINGS);
    const screen = await renderSection();

    await expect.element(screen.getByText("CloudFone AuthKey")).toBeVisible();
    await expect
      .element(
        screen.getByRole("textbox", { name: "Danh sách email người nhận" }),
      )
      .toHaveValue("quanly@vp.vn");
    await expect
      .element(screen.getByRole("textbox", { name: "CloudFone ServiceName" }))
      .toHaveValue("CloudFone");
    await expect
      .element(screen.getByRole("textbox", { name: "CloudFone AuthUser" }))
      .toHaveValue("ods-user");
    await expect.element(screen.getByText(/ODS đang bật/)).toBeVisible();
  });

  it("reports the integration as off while config is incomplete", async () => {
    mocks.loadOdsSettings.mockResolvedValue({
      service_name: "CloudFone",
      auth_user: "",
      auth_key: { configured: false, preview: null },
      recipients: [],
      enabled: false,
    });
    const screen = await renderSection();
    await expect.element(screen.getByText(/ODS đang tắt/)).toBeVisible();
    await expect
      .element(
        screen.getByText(
          /cần đủ ServiceName, AuthUser, AuthKey và ít nhất một người nhận/,
        ),
      )
      .toBeVisible();
  });

  it("saves a parsed recipient list plus the typed credentials", async () => {
    mocks.loadOdsSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.saveOdsSettings.mockResolvedValue(STORED_SETTINGS);
    const screen = await renderSection();

    await screen
      .getByRole("textbox", { name: "Danh sách email người nhận" })
      .fill("quanly@vp.vn, kd@vp.vn");
    await screen
      .getByRole("textbox", { name: "CloudFone AuthUser" })
      .fill("ods-user-2");
    await screen
      .getByRole("textbox", { name: /CloudFone AuthKey/ })
      .fill("cf-new-key");
    await screen.getByRole("button", { name: "Lưu cấu hình" }).click();

    await expect
      .poll(() => mocks.saveOdsSettings.mock.calls)
      .toEqual([
        [
          {
            auth_user: "ods-user-2",
            auth_key: "cf-new-key",
            recipients: ["quanly@vp.vn", "kd@vp.vn"],
          },
        ],
      ]);
  });

  it("saves the cron toggle through the same save", async () => {
    mocks.loadOdsSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.saveOdsSettings.mockResolvedValue({
      ...STORED_SETTINGS,
      enabled: false,
    });
    const screen = await renderSection();

    await screen.getByRole("button", { name: "Tắt cron" }).click();
    await screen.getByRole("button", { name: "Lưu cấu hình" }).click();

    await expect
      .poll(() => mocks.saveOdsSettings.mock.calls)
      .toEqual([
        [
          {
            recipients: ["quanly@vp.vn"],
            enabled: false,
          },
        ],
      ]);
    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([["Đã lưu. Tích hợp ODS đang tắt.", { type: "info" }]]);
  });

  it("probes the typed credentials first when testing the connection", async () => {
    mocks.loadOdsSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.testOdsConnection.mockResolvedValue({
      ok: true,
      configured: true,
      missing: [],
      latency_ms: 412,
      error: null,
    });
    const screen = await renderSection();

    await screen
      .getByRole("textbox", { name: /CloudFone AuthKey/ })
      .fill("typed-key");
    await screen.getByRole("button", { name: "Kiểm tra kết nối" }).click();

    await expect
      .poll(() => mocks.testOdsConnection.mock.calls)
      .toEqual([[{ auth_key: "typed-key" }]]);
    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([
        ["Kết nối CloudFone thành công (412 ms).", { type: "success" }],
      ]);
  });

  it("surfaces a failed probe without losing the stored credentials", async () => {
    mocks.loadOdsSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.testOdsConnection.mockResolvedValue({
      ok: false,
      configured: true,
      missing: [],
      latency_ms: 90,
      error: "CloudFone từ chối yêu cầu: Invalid AuthKey",
    });
    const screen = await renderSection();

    await screen.getByRole("button", { name: "Kiểm tra kết nối" }).click();
    await expect
      .poll(() => mocks.testOdsConnection.mock.calls)
      .toEqual([[undefined]]);
    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([
        [
          "Kết nối thất bại: CloudFone từ chối yêu cầu: Invalid AuthKey",
          { type: "error" },
        ],
      ]);
  });
});
