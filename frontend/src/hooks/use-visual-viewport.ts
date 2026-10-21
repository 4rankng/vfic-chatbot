import { useEffect } from "react";

/**
 * The height of the visual viewport in CSS pixels, updated on the root
 * element as `--visual-viewport-height`.
 *
 * Two consumers rely on it:
 *
 * - the app's modal kit sizes its bottom sheets and centered dialogs against
 *   it, so an open on-screen keyboard (which shrinks `visualViewport` but not
 *   `dvh` on iOS Safari) cannot cover the dialog's fields;
 * - the auth shell sizes its card against it so the sign-in button stays
 *   above the keyboard.
 *
 * `dvh` is the fallback everywhere: it already tracks mobile browser chrome
 * (URL bar collapse), and desktop browsers have no keyboard inset to track.
 */
const VISUAL_VIEWPORT_VARIABLE = "--visual-viewport-height";

const readHeight = (): number | null => {
  const viewport = window.visualViewport;
  return viewport ? Math.round(viewport.height) : null;
};

const publish = (height: number | null): void => {
  const target = document.documentElement;
  if (height === null) {
    target.style.removeProperty(VISUAL_VIEWPORT_VARIABLE);
    return;
  }
  target.style.setProperty(VISUAL_VIEWPORT_VARIABLE, `${height}px`);
};

let subscribers = 0;
let detach: (() => void) | null = null;

const attach = (): (() => void) => {
  const viewport = window.visualViewport;
  if (!viewport) return () => {};

  const onChange = () => publish(readHeight());
  viewport.addEventListener("resize", onChange);
  viewport.addEventListener("scroll", onChange);
  onChange();

  return () => {
    viewport.removeEventListener("resize", onChange);
    viewport.removeEventListener("scroll", onChange);
  };
};

/**
 * Keeps `--visual-viewport-height` on `<html>` in sync for as long as the
 * caller is mounted. Multiple callers share one listener set; the variable
 * is removed when the last one unmounts.
 */
export function useVisualViewportHeight(): void {
  useEffect(() => {
    subscribers += 1;
    if (!detach) detach = attach();

    return () => {
      subscribers -= 1;
      if (subscribers === 0 && detach) {
        detach();
        detach = null;
        publish(null);
      }
    };
  }, []);
}
