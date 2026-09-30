import { expect, test } from "./fixtures";

test.describe("current recruitment workspace baseline", () => {
  test("authenticates through FastAPI and renders the recruitment dashboard", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();

    await expect(
      page.getByRole("heading", { name: "Tổng quan" }),
    ).toBeVisible();
  });

  test("loads a real conversation and preserves takeover/release behavior", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/#/conversations");

    await expect(page.getByRole("heading", { name: "Hộp thư" })).toBeVisible({
      timeout: 15_000,
    });

    // Rendered guards carried over from the former stylesheet/component
    // source-text pins: the inbox must not resurrect the removed count badge
    // or queue-filter controls, and multi-line conversation rows must not be
    // shrunk into the fixed-height button system.
    const listMarkers = await page.evaluate(() => ({
      countBadge:
        document.querySelector(".workspace-conversation-count") !== null,
      queueFilters:
        document.querySelector(
          ".conversation-filters, .conversation-filter",
        ) !== null,
      shrunkRows: document.querySelector(".conversation.tt-btn") !== null,
      rows: document.querySelectorAll(".conversation").length,
    }));
    expect(listMarkers.queueFilters).toBe(false);
    expect(listMarkers.countBadge).toBe(false);
    expect(listMarkers.shrunkRows).toBe(false);
    expect(listMarkers.rows).toBeGreaterThan(0);

    await page
      .getByRole("button", { name: /Mở hội thoại với/ })
      .first()
      .click();
    await expect(
      page
        .getByRole("log", { name: "Luồng tin nhắn" })
        .getByText("E2E bot reply", { exact: true }),
    ).toBeVisible();

    // Directory-header density cap: every control in the inbox rail header is
    // 40px or less, and the adapter icon has to fit inside its tile.
    const detailMarkers = await page.evaluate(() => {
      const computed = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) return null;
        const styles = getComputedStyle(element);
        return {
          width: styles.width,
          height: styles.height,
        };
      };
      const searchInput = document.querySelector<HTMLElement>(
        ".workspace-rail .search input",
      );
      return {
        adapterTile: computed(".channel-adapter-option"),
        adapter: computed(".channel-adapter-option img"),
        modeIcon: computed(".mode-menu-trigger-icon .icon"),
        adapterCount: document.querySelectorAll(".channel-adapter-option")
          .length,
        searchHeight: searchInput ? getComputedStyle(searchInput).height : null,
      };
    });
    expect(detailMarkers.adapterCount).toBeGreaterThan(0);
    expect(detailMarkers.adapterTile).not.toBeNull();
    expect(detailMarkers.adapter).not.toBeNull();
    expect(detailMarkers.modeIcon).not.toBeNull();
    expect(detailMarkers.searchHeight).not.toBeNull();

    const tile = detailMarkers.adapterTile as { width: string; height: string };
    const icon = detailMarkers.adapter as { width: string; height: string };
    expect(Number.parseFloat(tile.width)).toBeLessThanOrEqual(40);
    expect(Number.parseFloat(tile.height)).toBeLessThanOrEqual(40);
    expect(Number.parseFloat(icon.width)).toBeLessThanOrEqual(
      Number.parseFloat(tile.width),
    );
    expect(
      Number.parseFloat(detailMarkers.searchHeight as string),
    ).toBeLessThanOrEqual(40);
    expect(Number.parseFloat(detailMarkers.modeIcon.width)).toBeGreaterThan(10);

    await page.getByRole("button", { name: "Đổi chế độ trả lời" }).click();
    const takeOverResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/take-over") && response.status() === 200,
    );
    await page.getByRole("menuitem").filter({ hasText: "Tư vấn viên" }).click();
    await takeOverResponse;
    await expect(
      page.getByRole("button", { name: "Đổi chế độ trả lời" }),
    ).toContainText("Tư vấn viên");

    await page.getByRole("button", { name: "Đổi chế độ trả lời" }).click();
    const releaseResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/release") && response.status() === 200,
    );
    await page
      .getByRole("menuitem", { name: "Chatbot Chatbot tự động xử lý" })
      .click();
    await releaseResponse;
    await expect(
      page.getByRole("button", { name: "Đổi chế độ trả lời" }),
    ).toContainText("Chatbot");
  });
});
