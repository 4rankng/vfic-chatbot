import { cleanup, render } from "vitest-browser-react";
import { afterEach, describe, expect, it } from "vitest";

import { useVisualViewportHeight } from "./use-visual-viewport";

/** Mounts the hook the way the app does (one caller, then gone). */
const Probe = () => {
  useVisualViewportHeight();
  return null;
};

const publishedValue = () =>
  document.documentElement.style.getPropertyValue("--visual-viewport-height");

const setVisualViewportHeight = (height: number) => {
  Object.defineProperty(window.visualViewport!, "height", {
    value: height,
    configurable: true,
  });
  window.visualViewport!.dispatchEvent(new Event("resize"));
};

afterEach(async () => {
  await cleanup();
});

describe("useVisualViewportHeight", () => {
  it("publishes the live visual viewport height on the root element", async () => {
    await render(<Probe />);

    // The hook reads the visual viewport itself, not innerHeight (they can
    // differ when browser chrome is visible).
    const initial = window.visualViewport!.height;
    expect(publishedValue()).toBe(`${Math.round(initial)}px`);

    // The iOS keyboard shrinks visualViewport without touching dvh — the
    // resize event is what the hook listens for.
    setVisualViewportHeight(initial - 300);
    expect(publishedValue()).toBe(`${Math.round(initial - 300)}px`);

    setVisualViewportHeight(initial);
    expect(publishedValue()).toBe(`${Math.round(initial)}px`);
  });

  it("removes the variable once the last caller unmounts", async () => {
    await render(<Probe />);
    expect(publishedValue()).not.toBe("");

    await cleanup();
    expect(publishedValue()).toBe("");
  });
});
