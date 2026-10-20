import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  loadCloudfoneSettings: vi.fn(),
  saveCloudfoneSettings: vi.fn(),
  testCloudfoneConnection: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
}));

vi.mock("./api", () => ({
  zaloIntegrationGateway: {
    loadCloudfoneSettings: mocks.loadCloudfoneSettings,
    saveCloudfoneSettings: mocks.saveCloudfoneSettings,
    testCloudfoneConnection: mocks.testCloudfoneConnection,
  },
}));

import { CloudfoneSection } from "./CloudfoneSection";

const STORED_SETTINGS = {
  service_name: "CloudFone",
  auth_user: "cloudfone-user",
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
      <CloudfoneSection />
    </QueryClientProvider>,
  );
  return screen;
};

afterEach(async () => {
  await cleanup();
  mocks.loadCloudfoneSettings.mockReset();
  mocks.saveCloudfoneSettings.mockReset();
  mocks.testCloudfoneConnection.mockReset();
  mocks.notify.mockClear();
});

describe("CloudfoneSection", () => {
  it("opens the transcripts viewer from the footer button", async () => {
    mocks.loadCloudfoneSettings.mockResolvedValue(STORED_SETTINGS);
    const onOpenTranscripts = vi.fn();
    const screen = await render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <CloudfoneSection onOpenTranscripts={onOpenTranscripts} />
      </QueryClientProvider>,
    );

    await screen.getByRole("button", { name: "Xem bản ghi cuộc gọi" }).click();
    expect(onOpenTranscripts).toHaveBeenCalled();
  });

  it("renders the stored configuration and the daily status line", async () => {
    mocks.loadCloudfoneSettings.mockResolvedValue(STORED_SETTINGS);
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
      .toHaveValue("cloudfone-user");
    await expect.element(screen.getByText(/Cloudfone đang bật/)).toBeVisible();
  });

  it("reports the integration as off while config is incomplete", async () => {
    mocks.loadCloudfoneSettings.mockResolvedValue({
      service_name: "CloudFone",
      auth_user: "",
      auth_key: { configured: false, preview: null },
      recipients: [],
      enabled: false,
    });
    const screen = await renderSection();
    await expect.element(screen.getByText(/Cloudfone đang tắt/)).toBeVisible();
    await expect
      .element(
        screen.getByText(
          /cần đủ ServiceName, AuthUser, AuthKey và ít nhất một người nhận/,
        ),
      )
      .toBeVisible();
  });

  it("saves a parsed recipient list plus the typed credentials", async () => {
    mocks.loadCloudfoneSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.saveCloudfoneSettings.mockResolvedValue(STORED_SETTINGS);
    const screen = await renderSection();

    await screen
      .getByRole("textbox", { name: "Danh sách email người nhận" })
      .fill("quanly@vp.vn, kd@vp.vn");
    await screen
      .getByRole("textbox", { name: "CloudFone AuthUser" })
      .fill("cloudfone-user-2");
    await screen
      .getByRole("textbox", { name: /CloudFone AuthKey/ })
      .fill("cf-new-key");
    await screen.getByRole("button", { name: "Lưu cấu hình" }).click();

    await expect
      .poll(() => mocks.saveCloudfoneSettings.mock.calls)
      .toEqual([
        [
          {
            auth_user: "cloudfone-user-2",
            auth_key: "cf-new-key",
            recipients: ["quanly@vp.vn", "kd@vp.vn"],
          },
        ],
      ]);
  });

  it("saves the cron toggle through the same save", async () => {
    mocks.loadCloudfoneSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.saveCloudfoneSettings.mockResolvedValue({
      ...STORED_SETTINGS,
      enabled: false,
    });
    const screen = await renderSection();

    await screen.getByRole("button", { name: "Tắt cron" }).click();
    await screen.getByRole("button", { name: "Lưu cấu hình" }).click();

    await expect
      .poll(() => mocks.saveCloudfoneSettings.mock.calls)
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
      .toEqual([["Đã lưu. Tích hợp Cloudfone đang tắt.", { type: "info" }]]);
  });

  it("probes the typed credentials first when testing the connection", async () => {
    mocks.loadCloudfoneSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.testCloudfoneConnection.mockResolvedValue({
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
      .poll(() => mocks.testCloudfoneConnection.mock.calls)
      .toEqual([[{ auth_key: "typed-key" }]]);
    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([
        ["Kết nối CloudFone thành công (412 ms).", { type: "success" }],
      ]);
  });

  it("surfaces a failed probe without losing the stored credentials", async () => {
    mocks.loadCloudfoneSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.testCloudfoneConnection.mockResolvedValue({
      ok: false,
      configured: true,
      missing: [],
      latency_ms: 90,
      error: "CloudFone từ chối yêu cầu: Invalid AuthKey",
    });
    const screen = await renderSection();

    await screen.getByRole("button", { name: "Kiểm tra kết nối" }).click();
    await expect
      .poll(() => mocks.testCloudfoneConnection.mock.calls)
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
