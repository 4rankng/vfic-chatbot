import { useEffect, useRef, type ReactNode } from "react";
import { Dialog, Modal, ModalOverlay } from "react-aria-components";

import { cx } from "@/utils/cx";

/**
 * Full-screen mobile transcript surface (owner decision 23/10 09:24): the
 * conversation stops living in a draggable bottom sheet and takes the whole
 * viewport instead — reading a transcript should feel like reading a chat,
 * not peeking under a sheet. Only the Cloudfone transcripts viewer mounts
 * it; the generic `BottomSheet` stays available for other surfaces.
 *
 * Contract:
 * - covers 100% of the visual viewport (`--visual-viewport-height` published
 *   by App on `<html>`, `100dvh` fallback) so the bubbles own every pixel
 *   below the header;
 * - one fixed ~56px header row (back | number · duration • date | copy-all,
 *   44px touch targets) and a scrolling body that fills the rest, with the
 *   iOS standalone safe-area padding at the bottom;
 * - slides in from the right over a 40% scrim in 200ms — the settings
 *   drill-down's list→thread motion (`slideout-menus`), not a sheet rise —
 *   and slides back out on exit;
 * - React Aria owns `aria-modal`, the focus trap and dismissal (Escape /
 *   scrim), exactly like the sheet before it — no hand-rolled focus code.
 *
 * Height is an inline `calc()`-free `var()` (same mechanism as the sheet and
 * the vendored modal kit) so the Tailwind-less test lane can read it off
 * `element.style` instead of depending on compiled CSS.
 */
type TranscriptFullscreenProps = {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  /** Accessible name of the modal dialog (the record it shows). */
  title: string;
  /** Header row: back action + identifiers + copy-all. Owns its geometry. */
  header: ReactNode;
  children: ReactNode;
};

export const TranscriptFullscreen = ({
  isOpen,
  onOpenChange,
  title,
  header,
  children,
}: TranscriptFullscreenProps) => {
  const dialogRef = useRef<HTMLElement | null>(null);

  // Stamp `aria-modal` on the dialog node whenever the overlay is up (same
  // reason as the sheet: React Aria's Dialog filters raw DOM props, and the
  // modal polyfill scans portal subtrees for exactly `[aria-modal="true"]`).
  useEffect(() => {
    dialogRef.current?.setAttribute("aria-modal", "true");
  });

  return (
    <ModalOverlay
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      isDismissable
      className={(state) =>
        cx(
          "fixed inset-0 z-[80] flex justify-end bg-black/40 outline-hidden",
          state.isEntering && "duration-200 ease-out animate-in fade-in",
          state.isExiting && "duration-200 animate-out fade-out",
        )
      }
    >
      <Modal
        className={(state) =>
          cx(
            "transcript-fullscreen flex w-full flex-col overflow-hidden bg-white outline-hidden",
            state.isEntering &&
              "duration-200 ease-out animate-in slide-in-from-right",
            state.isExiting &&
              "duration-200 ease-out animate-out slide-out-to-right",
          )
        }
        style={{ height: "var(--visual-viewport-height, 100dvh)" }}
      >
        <Dialog
          ref={dialogRef}
          aria-label={title}
          className="flex min-h-0 flex-1 flex-col outline-hidden"
        >
          {header}
          <div className="transcript-fullscreen-body min-h-0 flex-1 overflow-y-auto overscroll-contain">
            {children}
          </div>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
};
