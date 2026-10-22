import { expect } from "vitest";

/**
 * Shared phone-containment contract: nothing scrolls sideways and no visible
 * control or text block spills past the surface's right edge. The surface is
 * the scrolling region the page renders into (each workspace names its own);
 * the document check guards against body-level overflow at the given viewport
 * width. Skips elements with no client rects (display:none desktop branches).
 */
export const expectContained = (
  container: HTMLElement,
  width: number,
  surfaceSelector = ".project-workspace-content",
) => {
  const surface = container.querySelector<HTMLElement>(surfaceSelector)!;
  expect(surface.scrollWidth).toBeLessThanOrEqual(surface.clientWidth + 1);
  expect(document.scrollingElement!.scrollWidth).toBeLessThanOrEqual(width + 1);
  for (const element of surface.querySelectorAll<HTMLElement>(
    "button, p, h2, h3, h4, summary",
  )) {
    if (element.getClientRects().length === 0) continue;
    // Off-canvas anatomy (the phone drill-down parks the detail pane at
    // translateX(105%)) is invisible by design; its transformed rect is not a
    // containment failure. `visibility` inherits, so descendants of a parked
    // pane are skipped too.
    if (getComputedStyle(element).visibility === "hidden") continue;
    expect(
      element.scrollWidth,
      element.textContent ?? element.tagName,
    ).toBeLessThanOrEqual(element.clientWidth + 1);
    expect(element.getBoundingClientRect().right).toBeLessThanOrEqual(
      surface.getBoundingClientRect().right + 1,
    );
  }
};
