/**
 * Pure math for the phone (<768px) inbox behaviors — keyboard occlusion and
 * swipe-back commit policy. Kept framework-free so both decisions are unit-
 * testable without a browser.
 */

/**
 * How many layout-viewport pixels the keyboard (or another visual-viewport
 * occluder) hides below the fold. iOS overlays the keyboard: the layout
 * viewport (innerHeight) keeps its height while `visualViewport` shrinks, so
 * the difference is the occlusion. Android resize mode shrinks both equally,
 * producing ~0 and letting the resized `dvh` heights do the work. Negative
 * rounding noise clamps to 0.
 */
export const visualViewportBottomInset = (
  layoutViewportHeight: number,
  visualViewportHeight: number,
  visualViewportOffsetTop: number,
): number => {
  const inset = Math.round(
    layoutViewportHeight - visualViewportHeight - visualViewportOffsetTop,
  );
  return Number.isFinite(inset) && inset > 0 ? inset : 0;
};

export type SwipeCommitDecision = {
  /** Horizontal drag distance in px (>= 0). */
  dx: number;
  /** Drag duration in ms since touchstart. */
  dtMs: number;
  /** Width of the swiped pane in px. */
  width: number;
};

/** Distance (px) after which a slow drag is unambiguous. */
export const SWIPE_MIN_DRAG_PX = 48;
/** Fraction of the pane width that commits the back navigation. */
export const SWIPE_COMMIT_RATIO = 0.35;
/** Flick speed (px/ms) that commits with a short drag. */
export const SWIPE_FLICK_PX_PER_MS = 0.5;

/**
 * Commit the swipe-back when the drag covers at least 35% of the pane, or is
 * a flick (>= 0.5 px/ms) that still moved far enough to not be noise.
 */
export const shouldCommitSwipe = ({
  dx,
  dtMs,
  width,
}: SwipeCommitDecision): boolean => {
  if (
    !Number.isFinite(dx) ||
    !Number.isFinite(width) ||
    width <= 0 ||
    dx <= 0
  ) {
    return false;
  }
  if (dx >= width * SWIPE_COMMIT_RATIO) return true;
  return (
    dtMs > 0 && dx / dtMs >= SWIPE_FLICK_PX_PER_MS && dx >= SWIPE_MIN_DRAG_PX
  );
};
