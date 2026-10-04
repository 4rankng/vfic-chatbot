import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  loadEmailDigestSettings: vi.fn(),
  saveEmailDigestSettings: vi.fn(),
  testEmailDigest: vi.fn(),
}));

vi.mock("ra-core", () => ({
  useNotify: () => mocks.notify,
}));

vi.mock("./api", () => ({
  zaloIntegrationGateway: {
    loadEmailDigestSettings: mocks.loadEmailDigestSettings,
    saveEmailDigestSettings: mocks.saveEmailDigestSettings,
    testEmailDigest: mocks.testEmailDigest,
  },
}));

import { EmailDigestSection } from "./EmailDigestSection";

const STORED_SETTINGS = {
  resend_api_key: { configured: true, preview: "5 ký tự" },
  recipients: ["hr@vp.vn"],
  frequency: "daily" as const,
  send_time: "09:00",
  enabled: true,
  last_sent_at: "2026-10-02T02:00:00+00:00",
};

const renderSection = async () => {
  const screen = render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <EmailDigestSection />
    </QueryClientProvider>,
  );
  return screen;
};

afterEach(async () => {
  await cleanup();
  mocks.loadEmailDigestSettings.mockReset();
  mocks.saveEmailDigestSettings.mockReset();
  mocks.testEmailDigest.mockReset();
  mocks.notify.mockClear();
});

describe("EmailDigestSection", () => {
  it("renders the stored configuration and enabled status", async () => {
    mocks.loadEmailDigestSettings.mockResolvedValue(STORED_SETTINGS);
    const screen = await renderSection();

    await expect.element(screen.getByText("Resend API key")).toBeVisible();
    await expect
      .element(
        screen.getByRole("textbox", { name: "Danh sách email người nhận" }),
      )
      .toHaveValue("hr@vp.vn");
    await expect.element(screen.getByText("Email đang bật.")).toBeVisible();
    await expect.element(screen.getByText(/Lần gửi gần nhất/)).toBeVisible();
  });

  it("reports the feature as off while the recipient list is empty", async () => {
    mocks.loadEmailDigestSettings.mockResolvedValue({
      ...STORED_SETTINGS,
      recipients: [],
      enabled: false,
    });
    const screen = await renderSection();
    await expect.element(screen.getByText(/Email đang tắt/)).toBeVisible();
  });

  it("saves a parsed recipient list with the schedule", async () => {
    mocks.loadEmailDigestSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.saveEmailDigestSettings.mockResolvedValue(STORED_SETTINGS);
    const screen = await renderSection();

    await screen
      .getByRole("textbox", { name: "Danh sách email người nhận" })
      .fill("hr@vp.vn, boss@vp.vn");
    await screen.getByRole("button", { name: "Lưu cấu hình" }).click();

    await expect
      .poll(() => mocks.saveEmailDigestSettings.mock.calls)
      .toEqual([
        [
          {
            resend_api_key: undefined,
            recipients: ["hr@vp.vn", "boss@vp.vn"],
            frequency: "daily",
            send_time: "09:00",
          },
        ],
      ]);
  });

  it("sends the test email and reports success", async () => {
    mocks.loadEmailDigestSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.testEmailDigest.mockResolvedValue({
      ok: true,
      configured: true,
      missing: [],
      error: null,
      provider_id: "test-pid",
      candidate_count: 3,
    });
    const screen = await renderSection();

    // The button stays disabled until the operator types a preview address.
    const button = screen.getByRole("button", { name: "Gửi email thử" });
    await expect.element(button).toBeDisabled();
    await screen
      .getByRole("textbox", { name: "Email nhận thử" })
      .fill("xem.truoc@congty.vn");
    await button.click();
    await expect
      .poll(() => mocks.testEmailDigest.mock.calls)
      .toEqual([["xem.truoc@congty.vn"]]);
    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([
        [
          "Đã gửi email thử tới xem.truoc@congty.vn (3 ứng viên).",
          { type: "success" },
        ],
      ]);
  });

  it("saves the cron toggle through the schedule save", async () => {
    mocks.loadEmailDigestSettings.mockResolvedValue(STORED_SETTINGS);
    mocks.saveEmailDigestSettings.mockResolvedValue({
      ...STORED_SETTINGS,
      enabled: false,
    });
    const screen = await renderSection();

    await expect.element(screen.getByText("Email đang bật.")).toBeVisible();
    await screen.getByRole("button", { name: "Tắt cron" }).click();
    await screen.getByRole("button", { name: "Lưu cấu hình" }).click();

    await expect
      .poll(() => mocks.saveEmailDigestSettings.mock.calls)
      .toEqual([
        [
          {
            recipients: ["hr@vp.vn"],
            frequency: "daily",
            send_time: "09:00",
            enabled: false,
          },
        ],
      ]);
    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([["Đã lưu. Email đang tắt.", { type: "info" }]]);
  });

  it("surfaces missing configuration from the test send", async () => {
    mocks.loadEmailDigestSettings.mockResolvedValue({
      ...STORED_SETTINGS,
      resend_api_key: { configured: false, preview: null },
      recipients: [],
      enabled: false,
    });
    mocks.testEmailDigest.mockResolvedValue({
      ok: false,
      configured: false,
      missing: ["resend_api_key"],
      error: null,
      provider_id: null,
      candidate_count: 0,
    });
    const screen = await renderSection();

    await screen
      .getByRole("textbox", { name: "Email nhận thử" })
      .fill("xem.truoc@congty.vn");
    await screen.getByRole("button", { name: "Gửi email thử" }).click();
    await expect
      .poll(() => mocks.notify.mock.calls)
      .toEqual([["Chưa cấu hình đủ: resend_api_key.", { type: "error" }]]);
  });
});
