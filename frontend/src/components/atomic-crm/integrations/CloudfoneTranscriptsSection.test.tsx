import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listCloudfoneTranscripts: vi.fn(),
  loadCloudfoneTranscript: vi.fn(),
}));

vi.mock("./api", () => ({
  zaloIntegrationGateway: {
    listCloudfoneTranscripts: mocks.listCloudfoneTranscripts,
    loadCloudfoneTranscript: mocks.loadCloudfoneTranscript,
  },
}));

import { CloudfoneTranscriptsSection } from "./CloudfoneTranscriptsSection";

const ROWS = [
  {
    call_id: "1790848955",
    day: "2026-10-01",
    started_at: "2026-10-01T17:02:35",
    caller: "0362698948",
    talk_seconds: 98,
    transcript_preview: "S1: Alo ạ? Khách hỏi về giá dịch vụ.",
    created_at: "2026-10-02T01:00:00",
  },
  {
    call_id: "1790818523",
    day: "2026-10-01",
    started_at: "2026-10-01T09:15:11",
    caller: "0902065233",
    talk_seconds: 45,
    transcript_preview: "S1: Dạ em nghe ạ.",
    created_at: "2026-10-02T01:00:00",
  },
];

const PAGE = { items: ROWS, total: 2, page: 1, page_size: 20 };

const renderSection = async () => {
  const onBack = vi.fn();
  const screen = await render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <CloudfoneTranscriptsSection onBack={onBack} />
    </QueryClientProvider>,
  );
  return { screen, onBack };
};

afterEach(async () => {
  await cleanup();
  mocks.listCloudfoneTranscripts.mockReset();
  mocks.loadCloudfoneTranscript.mockReset();
});

describe("CloudfoneTranscriptsSection", () => {
  it("renders the stored rows with Vietnam time and letter-style duration", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const { screen } = await renderSection();

    await expect.element(screen.getByText("01/10/2026 17:02")).toBeVisible();
    await expect.element(screen.getByText("0362698948")).toBeVisible();
    await expect.element(screen.getByText("1p38s")).toBeVisible();
    await expect.element(screen.getByText("0902065233")).toBeVisible();
    await expect.element(screen.getByText("45s")).toBeVisible();
  });

  it("opens the full transcript for a row and closes it again", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    mocks.loadCloudfoneTranscript.mockResolvedValue({
      ...ROWS[0],
      transcript: "S1: Alo ạ?\nS2: Chị cho em hỏi giá dịch vụ.",
    });
    const { screen } = await renderSection();

    const row = screen.getByRole("row", { name: /0362698948/ });
    await row.getByRole("button", { name: "Xem", exact: true }).click();

    await expect
      .poll(() => mocks.loadCloudfoneTranscript.mock.calls)
      .toEqual([["1790848955"]]);
    await expect
      .element(screen.getByText(/Chị cho em hỏi giá dịch vụ/))
      .toBeVisible();

    await screen
      .getByRole("button", { name: "Đóng bản ghi", exact: true })
      .click();
    await expect
      .element(screen.getByText(/Chị cho em hỏi giá dịch vụ/))
      .not.toBeInTheDocument();
  });

  it("filters by call day and phone fragment", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const { screen } = await renderSection();

    await screen.getByLabelText("Ngày cuộc gọi").fill("2026-10-01");
    await screen.getByRole("textbox", { name: "Số điện thoại" }).fill("036");
    await screen.getByRole("button", { name: "Lọc", exact: true }).click();

    await expect
      .poll(() => mocks.listCloudfoneTranscripts.mock.calls.at(-1)?.[0])
      .toEqual({ day: "2026-10-01", caller: "036", page: 1, page_size: 20 });

    await screen.getByRole("button", { name: "Xóa lọc", exact: true }).click();
    // Clearing filters resets the inputs and shows the unfiltered rows again
    // (the query cache serves them fresh within staleTime — no refetch).
    await expect
      .element(screen.getByRole("textbox", { name: "Số điện thoại" }))
      .toHaveValue("");
    await expect.element(screen.getByText("0362698948")).toBeVisible();
    await expect.element(screen.getByText("0902065233")).toBeVisible();
  });

  it("shows the storage empty state when nothing is stored yet", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    });
    const { screen } = await renderSection();

    await expect
      .element(screen.getByText("Chưa có bản ghi cuộc gọi"))
      .toBeVisible();
  });

  it("navigates back to the Cloudfone settings section", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const { screen, onBack } = await renderSection();

    await screen
      .getByRole("button", { name: "Quay lại cài đặt Cloudfone" })
      .click();
    expect(onBack).toHaveBeenCalled();
  });
});
