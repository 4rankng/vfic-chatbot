import { describe, expect, it } from "vitest";

import {
  INITIAL_CHAT_FIRST_ITEM_INDEX,
  firstItemIndexAfterPrepend,
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
});
