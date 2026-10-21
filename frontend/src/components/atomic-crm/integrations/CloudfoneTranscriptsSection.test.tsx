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

/** An empty day the system has never looked at — the viewer must fetch it. */
const UNCHECKED_DAY = {
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  day_state: {
    day: "2026-10-01",
    status: "unchecked" as const,
    call_count: 0,
    recordable_count: 0,
    transcript_count: 0,
    checked_at: null,
    error: null,
  },
};

/** A checked day whose calls carried no recording to transcribe. */
const CHECKED_DAY = {
  ...UNCHECKED_DAY,
  day_state: {
    ...UNCHECKED_DAY.day_state,
    status: "checked" as const,
    call_count: 3,
    recordable_count: 0,
    transcript_count: 0,
    checked_at: "2026-10-02T01:00:00",
  },
};

/** A checked day whose recordings could not be transcribed. */
const UNTRANSCRIBABLE_DAY = {
  ...CHECKED_DAY,
  day_state: {
    ...CHECKED_DAY.day_state,
    call_count: 3,
    recordable_count: 1,
    transcript_count: 0,
  },
};

/** A checked day without a single call. */
const CALL_FREE_DAY = {
  ...CHECKED_DAY,
  day_state: {
    ...CHECKED_DAY.day_state,
    call_count: 0,
    recordable_count: 0,
    transcript_count: 0,
  },
};

const BACKFILLED = {
  day: "2026-10-01",
  status: "checked" as const,
  calls: 3,
  recordable: 1,
  transcripts: 1,
  added: 1,
  remaining: 0,
  message: null,
};

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
  mocks.backfillCloudfoneTranscripts.mockReset();
  await page.viewport(1280, 720);
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

  it("fetches a day from Cloudfone when the system has never checked it", async () => {
    // The daily pass only covers the previous day, so an older day the admin
    // opens has no stored transcripts — the viewer pulls it from the vendor.
    mocks.listCloudfoneTranscripts.mockResolvedValue(UNCHECKED_DAY);
    mocks.backfillCloudfoneTranscripts.mockResolvedValue(BACKFILLED);
    const { screen } = await renderSection();

    await screen.getByLabelText("Ngày cuộc gọi").fill("2026-10-01");

    await expect
      .poll(() => mocks.backfillCloudfoneTranscripts.mock.calls.at(-1)?.[0])
      .toEqual({ day: "2026-10-01", force: false });
    // The list is refreshed once the day is stored.
    await expect
      .poll(() => mocks.listCloudfoneTranscripts.mock.calls.length)
      .toBeGreaterThan(1);
  });

  it("does not fetch a day the system already checked", async () => {
    // The marker says the day is known — and it holds nothing, so there is
    // nothing to fetch.
    mocks.listCloudfoneTranscripts.mockResolvedValue(CHECKED_DAY);
    const { screen } = await renderSection();

    await screen.getByLabelText("Ngày cuộc gọi").fill("2026-10-01");

    await expect
      .element(screen.getByText("Ngày này không có bản ghi"))
      .toBeVisible();
    expect(mocks.backfillCloudfoneTranscripts).not.toHaveBeenCalled();
  });

  it("explains a day whose recordings could not be transcribed", async () => {
    // The vendor clip was unusable (too short / broken), so the day holds no
    // transcript — the admin needs to see that, not a bare "nothing here".
    mocks.listCloudfoneTranscripts.mockResolvedValue(UNTRANSCRIBABLE_DAY);
    const { screen } = await renderSection();

    await screen.getByLabelText("Ngày cuộc gọi").fill("2026-10-01");

    await expect
      .element(screen.getByText("Không chuyển được bản ghi sang văn bản"))
      .toBeVisible();
    await expect
      .element(
        screen.getByText(
          /1 cuộc gọi có bản ghi nhưng không chuyển sang văn bản/,
        ),
      )
      .toBeVisible();
  });

  it("explains a day without a single call", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue(CALL_FREE_DAY);
    const { screen } = await renderSection();

    await screen.getByLabelText("Ngày cuộc gọi").fill("2026-10-01");

    await expect
      .element(screen.getByText(/không có cuộc gọi nào/))
      .toBeVisible();
  });

  it("shows the fetch progress while a day is being pulled", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue(UNCHECKED_DAY);
    // The fetch stays pending — a real one downloads recordings and transcribes.
    mocks.backfillCloudfoneTranscripts.mockReturnValue(new Promise(() => {}));
    const { screen } = await renderSection();

    await screen.getByLabelText("Ngày cuộc gọi").fill("2026-10-01");

    await expect
      .element(screen.getByText("Đang tải bản ghi từ Cloudfone"))
      .toBeVisible();
  });

  it("offers the most recent day when nothing is stored at all", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    });
    mocks.backfillCloudfoneTranscripts.mockResolvedValue(BACKFILLED);
    const { screen } = await renderSection();

    await expect
      .element(screen.getByText("Chưa có bản ghi cuộc gọi"))
      .toBeVisible();
    await screen
      .getByRole("button", { name: "Tải bản ghi ngày gần nhất" })
      .click();

    await expect
      .poll(() => mocks.backfillCloudfoneTranscripts.mock.calls.at(-1)?.[0])
      .toEqual({ day: expect.any(String), force: true });
  });
  it("swaps the table for a selectable card list at phone width", async () => {
    await page.viewport(390, 844);
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const { screen } = await renderSection();

    await expect.element(screen.getByRole("listitem").first()).toBeVisible();
    // The phone surface renders no table at all — one surface per width.
    expect(
      screen.container.querySelector('[role="table"], [role="grid"]'),
    ).toBeNull();
    await expect.element(screen.getByText("1p38s")).toBeVisible();
    await expect.element(screen.getByText("đã lưu").first()).toBeVisible();

    const card = screen.getByRole("button", { name: /0362698948/ });
    mocks.loadCloudfoneTranscript.mockResolvedValue({
      ...ROWS[0],
      transcript: "S1: Alo ạ?\nS2: Hỏi giá dịch vụ.",
    });
    await card.click();

    await expect
      .poll(() => mocks.loadCloudfoneTranscript.mock.calls)
      .toEqual([["1790848955"]]);
    await expect.element(card).toHaveAttribute("aria-selected", "true");
    await expect.element(screen.getByText(/Hỏi giá dịch vụ/)).toBeVisible();

    await screen
      .getByRole("button", { name: "Đóng bản ghi", exact: true })
      .click();
    await expect.element(card).toHaveAttribute("aria-selected", "false");
  });

  it("stacks the filters and shows a compact pager at phone width", async () => {
    await page.viewport(390, 844);
    // 21 rows → two pages, so the compact pager has somewhere to go.
    const manyRows = Array.from({ length: 21 }, (_, index) => ({
      ...ROWS[index % ROWS.length],
      call_id: `call-${index}`,
      caller: `09000000${String(index).padStart(2, "0")}`,
    }));
    mocks.listCloudfoneTranscripts.mockResolvedValue({
      items: manyRows.slice(0, 20),
      total: 21,
      page: 1,
      page_size: 20,
    });
    const { screen } = await renderSection();
    await expect.element(screen.getByText("1p38s").first()).toBeVisible();

    // Stacked filter bar: both field wrappers and the submit button go
    // full-width (Tailwind classes are asserted, not computed widths —
    // the vitest browser project compiles no CSS).
    const form = screen.container.querySelector("form");
    expect(form?.classList.contains("flex-col")).toBe(true);
    expect(form?.classList.contains("items-stretch")).toBe(true);
    const fieldWrappers = [
      ...(form?.querySelectorAll(":scope > div") ?? []),
    ].filter((div) => div.querySelector("input") !== null);
    expect(fieldWrappers).toHaveLength(2);
    for (const wrapper of fieldWrappers) {
      expect(wrapper.classList.contains("w-full")).toBe(true);
    }
    const submit = form?.querySelector('button[type="submit"]');
    expect(submit?.classList.contains("w-full")).toBe(true);

    // Compact pager: Trước/Sau text buttons + "1/1", no page-number window.
    await expect
      .element(screen.getByRole("button", { name: "Trước", exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Sau", exact: true }))
      .toBeVisible();

    // Page 1 — prev is disabled, so no new query can fire from it.
    await expect
      .element(screen.getByRole("button", { name: "Trước", exact: true }))
      .toBeDisabled();

    await screen.getByRole("button", { name: "Sau", exact: true }).click();
    await expect
      .poll(() => mocks.listCloudfoneTranscripts.mock.calls.at(-1)?.[0])
      .toEqual({ day: undefined, caller: undefined, page: 2, page_size: 20 });
  });

  it("keeps the desktop pager and inline filter row at desktop width", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const { screen } = await renderSection();

    // Inline (not stacked) filter row, desktop pagination window. Wait for
    // the async list render before probing the container synchronously.
    await expect.element(screen.getByText("0362698948")).toBeVisible();
    const form = screen.container.querySelector("form");
    expect(form?.classList.contains("flex-col")).toBe(false);
    expect(
      screen.container.querySelector('[role="table"], [role="grid"]'),
    ).not.toBeNull();
    expect(
      screen.container.querySelector('button[aria-label="Về trang trước"]'),
    ).not.toBeNull();
  });

  it("hides Xóa lọc until a filter is active", async () => {
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const { screen } = await renderSection();

    expect(
      [...screen.container.querySelectorAll("button")].some(
        (button) => button.textContent?.trim() === "Xóa lọc",
      ),
    ).toBe(false);

    await screen.getByRole("textbox", { name: "Số điện thoại" }).fill("036");
    await screen.getByRole("button", { name: "Lọc", exact: true }).click();
    await expect
      .element(screen.getByRole("button", { name: "Xóa lọc", exact: true }))
      .toBeVisible();
  });
});
