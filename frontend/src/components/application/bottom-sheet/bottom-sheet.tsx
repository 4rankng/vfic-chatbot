import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { Dialog, Modal, ModalOverlay } from "react-aria-components";

import { cx } from "@/utils/cx";

/**
 * Modal bottom sheet — the mobile transcript surface and any future
 * long-form modal content share it (`frontend/AGENTS.md` § UI/UX Component
 * Sourcing: geometry comes from the design consult, tokens from the console's
 * UUI layer).
 *
 * Contract (settings-mobile consult, §3):
 * - slides up from the bottom edge over a 40% scrim; tapping the scrim or
 *   pressing Escape dismisses (`isDismissable`), the same path a drag below
 *   the minimum would take if one were wired later;
 * - starts at 50% of the visual viewport and the grip drags it to 90%
 *   (two detents, snap-to-nearest on release);
 * - React Aria owns `aria-modal`, the focus trap and dismissal, exactly like
 *   the console's other modal surfaces — no hand-rolled focus code here.
 *
 * Height is an inline `calc()` over `--visual-viewport-height` (App publishes
 * it on `<html>`, `dvh` fallback) so an on-screen keyboard cannot cover the
 * sheet body — same mechanism as the vendored modal kit.
 *
 * Only the grip drags. The body keeps native scrolling: one gesture surface,
 * one scroll surface, no arbitration code.
 */

/** Start and full detents, as fractions of the visual viewport. */
const DETENTS = [0.5, 0.9] as const;

type BottomSheetProps = {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  /** Accessible name of the modal dialog (the record it shows). */
  title: string;
  /** Header row: identifiers left, actions right. Sits below the grip. */
  header: ReactNode;
  children: ReactNode;
};

export const BottomSheet = ({
  isOpen,
  onOpenChange,
  title,
  header,
  children,
}: BottomSheetProps) => {
  const [ratio, setRatio] = useState<number>(DETENTS[0]);
  const [dragging, setDragging] = useState(false);
  const dialogRef = useRef<HTMLElement | null>(null);
  const drag = useRef<{
    startY: number;
    startRatio: number;
    viewportHeight: number;
  }>({ startY: 0, startRatio: DETENTS[0], viewportHeight: 1 });

  // Stamp `aria-modal` on the dialog node whenever the sheet is up (see the
  // note by the Dialog below for why this cannot be declarative).
  useEffect(() => {
    dialogRef.current?.setAttribute("aria-modal", "true");
  });

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;

    const viewportHeight =
      window.visualViewport?.height ?? (window.innerHeight || 1);
    drag.current = {
      startY: event.clientY,
      startRatio: ratio,
      viewportHeight,
    };

    const grip = event.currentTarget;
    // Pointer capture keeps receiving moves outside the grip. Synthetic test
    // events carry pointer ids the browser does not know, where capture throws
    // — the listeners registered below still receive every move dispatched on
    // the grip itself (the SheetDragHandle precedent in kit/app-modal).
    try {
      grip.setPointerCapture(event.pointerId);
    } catch {
      // Unknown pointer id: drag continues through the grip listeners.
    }
    setDragging(true);

    const onMove = (moveEvent: PointerEvent) => {
      const delta =
        (drag.current.startY - moveEvent.clientY) / drag.current.viewportHeight;
      const next = Math.min(
        DETENTS[1],
        Math.max(DETENTS[0], drag.current.startRatio + delta),
      );
      setRatio(next);
    };

    const onUp = () => {
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
      grip.removeEventListener("pointercancel", onUp);
      setDragging(false);
      setRatio((current) =>
        Math.abs(current - DETENTS[0]) <= Math.abs(current - DETENTS[1])
          ? DETENTS[0]
          : DETENTS[1],
      );
    };

    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
    grip.addEventListener("pointercancel", onUp);
  };

  return (
    <ModalOverlay
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      isDismissable
      className="fixed inset-0 z-[80] flex items-end justify-center bg-black/40 outline-hidden"
    >
      <Modal
        className={cx(
          "bottom-sheet flex w-full flex-col overflow-hidden rounded-t-xl bg-white outline-hidden",
          dragging ? "" : "transition-[height] duration-200 ease-out",
        )}
        style={{
          height: `calc(var(--visual-viewport-height, 100dvh) * ${ratio})`,
        }}
      >
        {/*
          React Aria's `Dialog` filters raw DOM props, so the W3C `aria-modal`
          flag the consult mandates cannot ride in as a declarative prop — and
          React Aria's own modal polyfill scans portal subtrees for exactly
          `[aria-modal="true"]`. The effect stamps it on the real dialog node;
          focus containment, Escape and scrim dismissal stay React Aria's.
        */}
        <Dialog
          ref={dialogRef}
          aria-label={title}
          className="flex min-h-0 flex-1 flex-col outline-hidden"
        >
          <div
            className="bottom-sheet-handle flex w-full cursor-grab touch-none flex-col items-center pb-2 pt-3 active:cursor-grabbing"
            onPointerDown={handlePointerDown}
            aria-hidden="true"
          >
            <span className="h-1 w-8 rounded-full bg-neutral-300" />
          </div>
          {header}
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            {children}
          </div>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
};
