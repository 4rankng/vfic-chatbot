import { useRef } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import type { ModalOverlayProps as AriaModalOverlayProps } from "react-aria-components";

import {
  Modal as UntitledModal,
  ModalOverlay as UntitledModalOverlay,
} from "@/components/application/modals/modal";
import { cx } from "@/utils/cx";

/**
 * Drag-to-dismiss handle for the mobile bottom sheet. Visual affordance plus
 * real pointer behaviour: dragging the sheet down past ~96px dismisses it
 * through the same Escape path React Aria already honours (so the overlay's
 * `isDismissable` / `isKeyboardDismissDisabled` guards keep applying), and a
 * short drag springs back. The handle assumes its parent element is the
 * sheet box — which is how `AppModal` renders it.
 */
export const SheetDragHandle = ({ className }: { className?: string }) => {
  const state = useRef({ startY: 0 });

  const handlePointerDown = (event: ReactPointerEvent<HTMLSpanElement>) => {
    const sheet = event.currentTarget.parentElement;
    if (!sheet) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;

    state.current.startY = event.clientY;
    const handle = event.currentTarget;
    // Pointer capture keeps receiving moves when the pointer leaves the
    // handle. Synthetic test events carry pointer ids the browser does not
    // know, where capture throws — the listeners registered on the handle
    // below still receive every move dispatched there.
    try {
      handle.setPointerCapture(event.pointerId);
    } catch {
      // Unknown pointer id: drag continues through the handle listeners.
    }
    sheet.classList.add("app-sheet-dragging");

    const distance = (clientY: number) =>
      Math.max(0, clientY - state.current.startY);

    const onMove = (moveEvent: PointerEvent) => {
      sheet.style.transform = `translateY(${distance(moveEvent.clientY)}px)`;
    };

    const finish = (upEvent: PointerEvent) => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      sheet.classList.remove("app-sheet-dragging");

      if (distance(upEvent.clientY) > 96) {
        sheet.style.transform = "";
        sheet.dispatchEvent(
          new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
        );
        return;
      }

      sheet.style.transition = "transform 200ms ease-out";
      sheet.style.transform = "";
      window.setTimeout(() => {
        sheet.style.transition = "";
      }, 220);
    };

    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  };

  return (
    <span
      aria-hidden="true"
      onPointerDown={handlePointerDown}
      className={cx("app-sheet-handle", className)}
    >
      <span className="app-sheet-handle-bar" />
    </span>
  );
};

/**
 * The console's dialog overlay: the vendored Untitled UI overlay, with the
 * phone-width (<sm) posture flipped from "floating card with gutters" to a
 * bottom sheet — flush against the bottom edge, edge-to-edge, sliding up.
 * `sm` and up keep the vendored centered geometry untouched.
 */
export const AppModalOverlay = (props: AriaModalOverlayProps) => (
  <UntitledModalOverlay
    {...props}
    className={(state) =>
      cx(
        // Base overrides ride variants so they win under 640px only; the
        // vendored file's own classes stay in charge at sm+.
        "max-sm:px-0 max-sm:pb-0",
        typeof props.className === "function"
          ? props.className(state)
          : props.className,
      )
    }
  />
);

type AppModalProps = AriaModalOverlayProps & {
  /** Extra classes for the sheet box (the vendored `Modal` element). */
  className?: AriaModalOverlayProps["className"];
  children?: ReactNode;
};

/**
 * The console's dialog surface: the vendored Untitled UI modal with a mobile
 * bottom-sheet posture under 640px — rounded top corners only, an 85%-of-
 * visual-viewport height cap (keyboard-aware via `--visual-viewport-height`),
 * a slide-up entrance and a drag handle. At `sm`+ the vendored centered
 * modal geometry applies unchanged.
 */
export const AppModal = ({ children, ...props }: AppModalProps) => (
  <UntitledModal
    {...props}
    className={(state) =>
      cx(
        "max-sm:flex max-sm:flex-col",
        "max-sm:rounded-none max-sm:rounded-t-xl",
        "max-sm:max-h-[calc(var(--visual-viewport-height,100dvh)*0.85)]",
        // Sheet motion, declared unconditionally because the custom
        // properties are inert without the `animate-in`/`animate-out` the
        // vendored modal only applies mid-transition: under 640px the sheet
        // slides up (zoom neutralised) and slides back down on exit; sm+
        // keeps the vendored zoom untouched.
        "max-sm:[--tw-enter-scale:1] max-sm:slide-in-from-bottom",
        "max-sm:[--tw-exit-scale:1] max-sm:slide-out-to-bottom",
        typeof props.className === "function"
          ? props.className(state)
          : props.className,
      )
    }
  >
    <SheetDragHandle />
    {children}
  </UntitledModal>
);
