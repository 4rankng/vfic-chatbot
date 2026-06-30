import { describe, expect, it } from "vitest";

import {
  INITIAL_CHAT_FIRST_ITEM_INDEX,
  estimateMessageRowHeight,
  firstItemIndexAfterPrepend,
  measuredOrEstimatedMessageRowHeight,
} from "./chatScrollIndex";

describe("chat scroll index helpers", () => {
  it("starts with headroom so prepending history can decrement safely", () => {
    expect(INITIAL_CHAT_FIRST_ITEM_INDEX).toBeGreaterThan(1000);
  });

  it("decrements firstItemIndex only by the number of actually prepended rows", () => {
    expect(firstItemIndexAfterPrepend(100_000, 3)).toBe(99_997);
    expect(firstItemIndexAfterPrepend(100_000, 0)).toBe(100_000);
  });

  it("never lets firstItemIndex go negative", () => {
    expect(firstItemIndexAfterPrepend(2, 10)).toBe(0);
  });

  it("estimates long multi-line messages as tall rows before Virtuoso measures them", () => {
    const shortHeight = estimateMessageRowHeight({
      type: "outbound",
      content: "Xin chào, em cần hỗ trợ gì?",
    });
    const longHeight = estimateMessageRowHeight({
      type: "outbound",
      content: Array.from(
        { length: 20 },
        (_, index) =>
          `${index + 1}. Tuyến xe bus có điểm đón và chính sách ca làm việc chi tiết.`,
      ).join("\n"),
    });

    expect(shortHeight).toBeGreaterThanOrEqual(48);
    expect(longHeight).toBeGreaterThan(400);
    expect(longHeight).toBeGreaterThan(shortHeight * 6);
  });

  it("accounts for soft wrapping when a policy message has few explicit newlines", () => {
    const height = estimateMessageRowHeight({
      type: "outbound",
      content:
        "Chính sách ứng tuyển: ứng viên cần chuẩn bị CCCD, số điện thoại liên hệ, khu vực sinh sống, kinh nghiệm làm việc, mong muốn ca làm, mức lương kỳ vọng, phương tiện đi lại và khả năng bắt đầu công việc trong tuần này.",
    });

    expect(height).toBeGreaterThan(100);
  });

  it("uses cached measured heights before falling back to estimates", () => {
    const measuredHeights = new Map([["m1", 384]]);
    const message = {
      id: "m1",
      type: "outbound" as const,
      content: "Short text",
    };

    expect(measuredOrEstimatedMessageRowHeight(message, measuredHeights)).toBe(
      384,
    );
    expect(
      measuredOrEstimatedMessageRowHeight(
        { ...message, id: "uncached" },
        measuredHeights,
      ),
    ).toBe(estimateMessageRowHeight(message));
  });
});
