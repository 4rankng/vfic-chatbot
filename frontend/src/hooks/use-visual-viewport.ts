import * as React from "react";

import { visualViewportBottomInset } from "@/components/atomic-crm/conversations/domain/phone-surface";

/**
 * Live bottom inset (px) the visual viewport loses to the on-screen keyboard.
 * 0 when `window.visualViewport` is unsupported (older browsers, jsdom-less
 * test shells). Subscribe on mount only — the values come from the window, so
 * no props may change the subscription.
 */
export function useVisualViewportInset(): number {
  const [inset, setInset] = React.useState(0);

  React.useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const update = () =>
      setInset(
        visualViewportBottomInset(
          window.innerHeight,
          viewport.height,
          viewport.offsetTop,
        ),
      );
    update();
    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    return () => {
      viewport.removeEventListener("resize", update);
      viewport.removeEventListener("scroll", update);
    };
  }, []);

  return inset;
}
