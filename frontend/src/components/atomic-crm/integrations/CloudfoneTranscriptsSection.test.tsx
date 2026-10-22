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
    // The vitest browser lane's default viewport (412x768) is a phone width;
    // this test asserts the DESKTOP table, so pin the desktop viewport the
    // afterEach normally leaves behind for later tests.
    await page.viewport(1280, 720);
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

  it("renders the phone filter surface: search, day-scope chips, call cards", async () => {
    await page.viewport(390, 844);
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const { screen } = await renderSection();

    // Search field (h-10/r10 geometry lives in cloudfone-transcripts.css).
    const search = screen.getByRole("searchbox", { name: "Tìm số điện thoại" });
    await expect.element(search).toBeVisible();
    expect(search.element().closest(".transcripts-search")).not.toBeNull();

    // Single-select day-scope chips; "Tất cả" starts active.
    await expect
      .element(screen.getByRole("radio", { name: "Tất cả" }))
      .toBeChecked();
    await expect
      .element(screen.getByRole("radio", { name: "Hôm nay" }))
      .not.toBeChecked();
    await expect
      .element(screen.getByRole("radio", { name: "Hôm qua" }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("radio", { name: "Chọn ngày" }))
      .toBeVisible();

    // One bordered card per call — no table at this width. Wait for the
    // mocked page first: the toolbar renders before the list resolves.
    await expect.element(screen.getByText("0362698948")).toBeVisible();
    expect(
      screen.container.querySelector('[role="table"], [role="grid"]'),
    ).toBeNull();
    expect(screen.container.querySelectorAll(".call-card")).toHaveLength(2);
    // The card's second line carries the duration pill; line 1 the 12-hour
    // time-of-day (consult §4: "10:45 SA" style, never the full date).
    expect(
      screen.container.querySelector(".call-card-badge")?.textContent,
    ).toBe("1p38s");
    expect(screen.container.querySelector(".call-card-name")?.textContent).toBe(
      "0362698948",
    );
    expect(screen.container.querySelector(".call-card-time")?.textContent).toBe(
      "5:02 CH",
    );

    // Compact pager below the cards.
    await expect
      .element(screen.getByRole("button", { name: "Trước", exact: true }))
      .toBeVisible();
    await expect
      .element(screen.getByRole("button", { name: "Sau", exact: true }))
      .toBeVisible();
  });

  it("follows the phone search with the caller filter after a 300ms pause", async () => {
    await page.viewport(390, 844);
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const { screen } = await renderSection();

    await screen
      .getByRole("searchbox", { name: "Tìm số điện thoại" })
      .fill("036");

    await expect
      .poll(() => mocks.listCloudfoneTranscripts.mock.calls.at(-1)?.[0])
      .toEqual({ day: undefined, caller: "036", page: 1, page_size: 20 });
  });

  it("switches day scope from the chips and reveals the date field on Chọn ngày", async () => {
    await page.viewport(390, 844);
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    const { screen } = await renderSection();

    await screen.getByRole("radio", { name: "Hôm nay" }).click();
    await expect
      .poll(() => mocks.listCloudfoneTranscripts.mock.calls.at(-1)?.[0])
      .toEqual({
        day: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        caller: undefined,
        page: 1,
        page_size: 20,
      });
    await expect
      .element(screen.getByRole("radio", { name: "Hôm nay" }))
      .toBeChecked();

    await screen.getByRole("radio", { name: "Chọn ngày" }).click();
    await expect.element(screen.getByLabelText("Ngày cuộc gọi")).toBeVisible();
  });

  it("opens the transcript in a draggable bottom sheet at phone width", async () => {
    await page.viewport(390, 844);
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    mocks.loadCloudfoneTranscript.mockResolvedValue({
      ...ROWS[0],
      transcript: "S1: Alo ạ?\nS2: Hỏi giá dịch vụ.",
    });
    const { screen } = await renderSection();

    await screen.getByRole("listitem").first().getByRole("button").click();

    const dialog = screen.getByRole("dialog");
    await expect.element(dialog).toBeVisible();
    // React Aria owns the modal contract (aria-modal + focus containment).
    expect(dialog.element().closest('[aria-modal="true"]')).not.toBeNull();
    // Header meta: "duration • date" (consult §1), never the old date-first
    // order.
    await expect
      .element(screen.getByText("1p38s • 01/10/2026 17:02"))
      .toBeVisible();
    await expect
      .poll(
        () =>
          dialog.element().contains(document.activeElement) ||
          document.activeElement === dialog.element(),
      )
      .toBe(true);
    await expect
      .poll(() => mocks.loadCloudfoneTranscript.mock.calls)
      .toEqual([["1790848955"]]);

    // Starts at the 50% detent; the grip drags it to the 92% detent.
    const sheet = dialog.element().parentElement as HTMLElement;
    expect(sheet.style.height).toContain("0.5");
    const grip = dialog
      .element()
      .querySelector<HTMLElement>(".bottom-sheet-handle")!;
    grip.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        clientY: 700,
        pointerId: 7,
        pointerType: "touch",
      }),
    );
    grip.dispatchEvent(
      new PointerEvent("pointermove", {
        bubbles: true,
        clientY: 480,
        pointerId: 7,
        pointerType: "touch",
      }),
    );
    grip.dispatchEvent(
      new PointerEvent("pointerup", {
        bubbles: true,
        clientY: 480,
        pointerId: 7,
        pointerType: "touch",
      }),
    );
    await expect.poll(() => sheet.style.height).toContain("0.92");

    await screen.getByRole("button", { name: "Đóng bản ghi" }).click();
    await expect.element(screen.getByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders the conversation as S1/S2 bubbles and copies all from the header", async () => {
    await page.viewport(390, 844);
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);
    mocks.loadCloudfoneTranscript.mockResolvedValue({
      ...ROWS[0],
      transcript: "S1: Alo ạ?\nS2: Hỏi giá dịch vụ.\nS2: Chị cho em 5 phút.",
    });
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });
    const { screen } = await renderSection();

    await screen.getByRole("listitem").first().getByRole("button").click();
    const dialog = screen.getByRole("dialog");
    await expect.element(dialog).toBeVisible();

    // S1 left on gray-100, S2 right on primary-50 (brand-50 in the UUI layer).
    const left = dialog.element().querySelectorAll(".transcript-bubble--left");
    const right = dialog
      .element()
      .querySelectorAll(".transcript-bubble--right");
    expect(left).toHaveLength(1);
    expect(right).toHaveLength(2);
    expect(left[0]?.className).toContain("bg-neutral-100");
    expect(right[0]?.className).toContain("bg-brand-50");
    expect(left[0]?.getAttribute("aria-label")).toBe("Speaker: S1. Alo ạ?");

    // 11px speaker labels, coloured per side (S1 neutral-500, S2 brand-600).
    const speakers = dialog.element().querySelectorAll(".transcript-speaker");
    expect(speakers[0]?.className).toContain("text-neutral-500");
    expect(speakers[1]?.className).toContain("text-brand-600");

    // Same-speaker turns sit closer (6px vs 12px — the is-continued class).
    expect(dialog.element().querySelectorAll(".is-continued")).toHaveLength(1);

    // Copy lives once, in the sheet header — the consult's bubble row is
    // label + text only.
    expect(dialog.element().querySelectorAll(".transcript-copy")).toHaveLength(
      0,
    );
    await screen
      .getByRole("button", { name: "Sao chép toàn bộ bản ghi" })
      .click();
    await expect
      .poll(() => clipboardWrite.mock.calls)
      .toEqual([["S1: Alo ạ?\nS2: Hỏi giá dịch vụ.\nS2: Chị cho em 5 phút."]]);
  });

  it("shows the sheet's three body states: skeletons, error + retry, empty", async () => {
    await page.viewport(390, 844);
    mocks.listCloudfoneTranscripts.mockResolvedValue(PAGE);

    // Loading: three alternating skeleton bubbles while the detail is pending.
    mocks.loadCloudfoneTranscript.mockReturnValue(new Promise(() => {}));
    const loading = await renderSection();
    await loading.screen
      .getByRole("listitem")
      .first()
      .getByRole("button")
      .click();
    const loadingDialog = loading.screen.getByRole("dialog");
    await expect.element(loadingDialog).toBeVisible();
    const skeletons = loadingDialog
      .element()
      .querySelectorAll(".transcript-skeleton-bubble");
    expect(skeletons).toHaveLength(3);
    expect(skeletons[0]?.className).toContain("is-left");
    expect(skeletons[1]?.className).toContain("is-right");
    expect(skeletons[2]?.className).toContain("is-left");
    expect(skeletons[0]?.getAttribute("style")).toContain("height: 48px");
    expect(skeletons[1]?.getAttribute("style")).toContain("height: 64px");
    expect(skeletons[2]?.getAttribute("style")).toContain("height: 40px");
    await loading.screen
      .getByRole("button", { name: "Đóng bản ghi", exact: true })
      .click();
    await cleanup();

    // Error: the consult's card with a working retry.
    mocks.loadCloudfoneTranscript.mockReset();
    mocks.loadCloudfoneTranscript
      .mockRejectedValueOnce(new Error("transcription broke"))
      .mockResolvedValue({
        ...ROWS[0],
        transcript: "S1: Alo ạ?",
      });
    const errored = await renderSection();
    await errored.screen
      .getByRole("listitem")
      .first()
      .getByRole("button")
      .click();
    await expect
      .element(errored.screen.getByText("Không thể tải hội thoại"))
      .toBeVisible();
    await expect
      .element(errored.screen.getByText(/bóc băng hoặc tải dữ liệu/))
      .toBeVisible();
    await errored.screen.getByRole("button", { name: "Thử lại" }).click();
    await expect.element(errored.screen.getByText(/^Alo ạ\?$/)).toBeVisible();
    await cleanup();

    // Empty: a stored call whose transcript parses to nothing.
    mocks.loadCloudfoneTranscript.mockReset();
    mocks.loadCloudfoneTranscript.mockResolvedValue({
      ...ROWS[0],
      transcript: "",
    });
    const empty = await renderSection();
    await empty.screen
      .getByRole("listitem")
      .first()
      .getByRole("button")
      .click();
    await expect
      .element(empty.screen.getByText("Chưa có nội dung cuộc gọi"))
      .toBeVisible();
    await expect
      .element(empty.screen.getByText(/Nội dung bóc băng sẽ hiển thị tại đây/))
      .toBeVisible();
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
