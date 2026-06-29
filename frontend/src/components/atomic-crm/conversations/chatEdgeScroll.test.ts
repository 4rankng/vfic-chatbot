import { describe, expect, it } from "vitest";

import {
  shouldPrefetchOlderMessages,
  shouldTrapEdgeWheel,
} from "./chatEdgeScroll";

describe("shouldTrapEdgeWheel", () => {
  const scroller = {
    clientHeight: 100,
    scrollHeight: 500,
  };

  it("traps upward wheel events at the top edge", () => {
    expect(shouldTrapEdgeWheel({ ...scroller, scrollTop: 0 }, -12)).toBe(true);
  });

  it("traps downward wheel events at the bottom edge", () => {
    expect(shouldTrapEdgeWheel({ ...scroller, scrollTop: 400 }, 12)).toBe(true);
  });

  it("does not trap normal wheel events away from the edges", () => {
    expect(shouldTrapEdgeWheel({ ...scroller, scrollTop: 200 }, -12)).toBe(
      false,
    );
    expect(shouldTrapEdgeWheel({ ...scroller, scrollTop: 200 }, 12)).toBe(
      false,
    );
  });

  it("contains wheel events when content is not scrollable", () => {
    expect(
      shouldTrapEdgeWheel(
        { scrollTop: 0, clientHeight: 500, scrollHeight: 500 },
        12,
      ),
    ).toBe(true);
  });
});

describe("shouldPrefetchOlderMessages", () => {
  const scroller = {
    clientHeight: 100,
    scrollHeight: 500,
  };

  it("prefetches while scrolling upward near the top", () => {
    expect(
      shouldPrefetchOlderMessages(
        { ...scroller, scrollTop: 80 },
        140,
        100,
      ),
    ).toBe(true);
  });

  it("does not prefetch away from the top threshold", () => {
    expect(
      shouldPrefetchOlderMessages(
        { ...scroller, scrollTop: 220 },
        260,
        100,
      ),
    ).toBe(false);
  });

  it("does not prefetch while scrolling downward", () => {
    expect(
      shouldPrefetchOlderMessages(
        { ...scroller, scrollTop: 80 },
        40,
        100,
      ),
    ).toBe(false);
  });
});
