import * as React from "react";

const MOBILE_BREAKPOINT = 768;
const WIDE_DESKTOP_BREAKPOINT = 1280;

// Read the media query synchronously so the very first render picks the correct
// shell — otherwise a phone paints the desktop frame for one frame before the
// effect corrects it (visible flash). Returns false during SSR / pre-hydration.
function readIsMobile(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`).matches;
}

export function useIsMobile() {
  const [isMobile, setIsMobile] = React.useState<boolean>(readIsMobile);

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    const onChange = () => {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    };
    mql.addEventListener("change", onChange);
    setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return isMobile;
}

function readIsWideDesktop(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia(`(min-width: ${WIDE_DESKTOP_BREAKPOINT}px)`).matches;
}

export function useIsWideDesktop() {
  const [isWideDesktop, setIsWideDesktop] =
    React.useState<boolean>(readIsWideDesktop);

  React.useEffect(() => {
    const mql = window.matchMedia(`(min-width: ${WIDE_DESKTOP_BREAKPOINT}px)`);
    const onChange = () => setIsWideDesktop(mql.matches);
    mql.addEventListener("change", onChange);
    setIsWideDesktop(mql.matches);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return isWideDesktop;
}
