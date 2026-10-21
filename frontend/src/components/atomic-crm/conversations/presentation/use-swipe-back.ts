import { useEffect, type RefObject } from "react";

import { shouldCommitSwipe } from "../domain/phone-surface";

const EDGE_PX = 24;
const AXIS_LOCK_PX = 8;

type SwipeBackOptions = {
  enabled: boolean;
  containerRef: RefObject<HTMLElement | null>;
  onBack: () => void;
};

/**
 * Edge-swipe back for the phone drill-down (<768px). A one-finger horizontal
 * drag starting within the left edge follows the finger and commits the back
 * navigation once it passes the swipe threshold (phone-surface.ts); vertical
 * gestures and touches away from the edge are released untouched so message
 * scrolling and row taps keep working. Cheap additive affordance — the Back
 * button and browser history stay the authoritative exits.
 */
export function useSwipeBack({
  enabled,
  containerRef,
  onBack,
}: SwipeBackOptions) {
  useEffect(() => {
    if (!enabled) return;
    const container = containerRef.current;
    if (!container) return;

    let pane: HTMLElement | null = null;
    let startX = 0;
    let startY = 0;
    let startMs = 0;
    let axis: "x" | "y" | null = null;

    const releasePane = () => {
      if (!pane) return;
      pane.style.transition = "";
      pane.style.transform = "";
      pane = null;
      axis = null;
    };

    const onTouchStart = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (!touch || event.touches.length !== 1) return;
      if (touch.clientX > EDGE_PX) return;
      pane = container.querySelector<HTMLElement>(".center-panel");
      if (!pane) return;
      startX = touch.clientX;
      startY = touch.clientY;
      startMs = event.timeStamp;
      axis = null;
    };

    const onTouchMove = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (!touch || !pane) return;
      const dx = touch.clientX - startX;
      const dy = touch.clientY - startY;
      if (axis === null) {
        if (Math.abs(dx) < AXIS_LOCK_PX && Math.abs(dy) < AXIS_LOCK_PX) return;
        axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
        if (axis === "y") {
          releasePane();
          return;
        }
      }
      if (axis !== "x" || dx <= 0) return;
      pane.style.transition = "none";
      pane.style.transform = `translateX(${dx}px)`;
    };

    const onTouchEnd = (event: TouchEvent) => {
      const touch = event.changedTouches[0];
      const activePane = pane;
      if (!touch || !activePane) {
        releasePane();
        return;
      }
      const dx = Math.max(0, touch.clientX - startX);
      const commit =
        axis === "x" &&
        shouldCommitSwipe({
          dx,
          dtMs: event.timeStamp - startMs,
          width: activePane.offsetWidth,
        });
      releasePane();
      if (commit) onBack();
    };

    container.addEventListener("touchstart", onTouchStart, { passive: true });
    container.addEventListener("touchmove", onTouchMove, { passive: true });
    container.addEventListener("touchend", onTouchEnd, { passive: true });
    container.addEventListener("touchcancel", onTouchEnd, { passive: true });
    return () => {
      container.removeEventListener("touchstart", onTouchStart);
      container.removeEventListener("touchmove", onTouchMove);
      container.removeEventListener("touchend", onTouchEnd);
      container.removeEventListener("touchcancel", onTouchEnd);
      releasePane();
    };
  }, [enabled, containerRef, onBack]);
}
