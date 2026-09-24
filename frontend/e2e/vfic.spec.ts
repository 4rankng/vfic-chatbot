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

    // Rendered guards carried over from the former tailkit-redesign.css
    // source-text pins: channel-adapter icons and the reply-mode trigger icon
    // render at all and grow to their 44px/20px mobile sizes on phones.
    const isMobile = page.viewportSize().width < 768;
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
      return {
        adapter: computed(".channel-adapter-option img"),
        modeIcon: computed(".mode-menu-trigger-icon .icon"),
        adapterCount: document.querySelectorAll(".channel-adapter-option")
          .length,
      };
    });
    expect(detailMarkers.adapterCount).toBeGreaterThan(0);
    expect(detailMarkers.adapter).not.toBeNull();
    expect(detailMarkers.modeIcon).not.toBeNull();
    if (isMobile) {
      expect(detailMarkers.adapter.width).toBe("44px");
      expect(detailMarkers.adapter.height).toBe("44px");
      expect(detailMarkers.modeIcon.width).toBe("20px");
      expect(detailMarkers.modeIcon.height).toBe("20px");
    } else {
      // Recorded desktop reality: the cascade renders the adapter icon at
      // 30px, not the 36px the removed source-text pins claimed.
      expect(detailMarkers.adapter.width).toBe("30px");
      expect(Number.parseFloat(detailMarkers.modeIcon.width)).toBeGreaterThan(
        10,
      );
    }

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
