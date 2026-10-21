import { describe, expect, it } from "vitest";

import {
  SWIPE_MIN_DRAG_PX,
  shouldCommitSwipe,
  visualViewportBottomInset,
} from "./phone-surface";

describe("visualViewportBottomInset", () => {
  it("reports the keyboard occlusion on iOS-style overlay keyboards", () => {
    // 844px layout viewport, keyboard leaves 500px visible, offset 0.
    expect(visualViewportBottomInset(844, 500, 0)).toBe(344);
  });

  it("accounts for the visual viewport offset when the sheet is panned", () => {
    expect(visualViewportBottomInset(844, 500, 100)).toBe(244);
  });

  it("is ~0 when the layout viewport already resized (Android resize mode)", () => {
    expect(visualViewportBottomInset(500, 500, 0)).toBe(0);
  });

  it("clamps negative rounding noise to 0", () => {
    expect(visualViewportBottomInset(500, 502, 0)).toBe(0);
  });
});

describe("shouldCommitSwipe", () => {
  const width = 390;

  it("commits when the drag covers >= 35% of the pane", () => {
    expect(shouldCommitSwipe({ dx: width * 0.35, dtMs: 600, width })).toBe(
      true,
    );
    expect(shouldCommitSwipe({ dx: 200, dtMs: 2000, width })).toBe(true);
  });

  it("commits a fast flick with enough distance", () => {
    expect(shouldCommitSwipe({ dx: SWIPE_MIN_DRAG_PX, dtMs: 60, width })).toBe(
      true,
    );
  });

  it("returns to the pane when the drag is short and slow", () => {
    expect(shouldCommitSwipe({ dx: 40, dtMs: 900, width })).toBe(false);
    expect(shouldCommitSwipe({ dx: 10, dtMs: 20, width })).toBe(false);
  });

  it("never commits zero, negative or widthless drags", () => {
    expect(shouldCommitSwipe({ dx: 0, dtMs: 10, width })).toBe(false);
    expect(shouldCommitSwipe({ dx: -20, dtMs: 10, width })).toBe(false);
    expect(shouldCommitSwipe({ dx: 200, dtMs: 10, width: 0 })).toBe(false);
    // A zero-duration drag never reaches the flick rule; without enough
    // distance it stays a non-committed gesture.
    expect(shouldCommitSwipe({ dx: SWIPE_MIN_DRAG_PX, dtMs: 0, width })).toBe(
      false,
    );
  });
});
