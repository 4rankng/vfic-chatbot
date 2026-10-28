import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listCloudfoneTranscripts: vi.fn(),
  loadCloudfoneTranscript: vi.fn(),
  backfillCloudfoneTranscripts: vi.fn(),
}));

vi.mock("./api", () => ({
  zaloIntegrationGateway: {
    listCloudfoneTranscripts: mocks.listCloudfoneTranscripts,
    loadCloudfoneTranscript: mocks.loadCloudfoneTranscript,
    backfillCloudfoneTranscripts: mocks.backfillCloudfoneTranscripts,
  },
}));

import { CallRecordsPage } from "./CallRecordsPage";

const PAGE = {
  items: [
    {
      call_id: "1790848955",
      day: "2026-10-01",
      started_at: "2026-10-01T17:02:35",
      caller: "0362698948",
      talk_seconds: 98,
      transcript_preview: "S1: Alo ạ? Khách hỏi về giá dịch vụ.",
      created_at: "2026-10-02T01:00:00",
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
};

afterEach(async () => {
  await cleanup();
  mocks.listCloudfoneTranscripts.mockReset();
  mocks.loadCloudfoneTranscript.mockReset();
  mocks.backfillCloudfoneTranscripts.mockReset();
  await page.viewport(1280, 720);
});

describe("CallRecordsPage", () => {
  it("opens the stored call records for every role, times on the Vietnam clock", async () => {
    // The desktop table needs the desktop viewport (same contract as the
    // section's own suite — the default lane viewport is a phone width).
    await page.viewport(1280, 720);
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const screen = await render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <CallRecordsPage />
      </QueryClientProvider>,
    );

    await expect
      .element(
        screen.getByRole("heading", {
          name: "Cloudfone · Bản ghi cuộc gọi",
          exact: true,
        }),
      )
      .toBeVisible();
    // CHAT-15 AC1 + ICT display: the row renders its ICT (GMT+7) wall-clock
    // time regardless of the browser's own zone.
    await expect.element(screen.getByText("01/10/2026 17:02")).toBeVisible();
  });

  it("carries no exit into the admin-only Cloudfone settings (CHAT-15 AC2)", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const screen = await render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <CallRecordsPage />
      </QueryClientProvider>,
    );

    await expect
      .element(
        screen.getByRole("button", { name: "Quay lại cài đặt Cloudfone" }),
      )
      .not.toBeInTheDocument();
  });
});
