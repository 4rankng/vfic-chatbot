import { useState } from "react";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import "@/index.css";
import { Dialog } from "@/components/application/modals/modal";
import { AppModal, AppModalOverlay } from "./app-modal";

/**
 * The console's modal surface. This project generates no Tailwind utilities
 * (see the note in layout/workspace-shell.test.tsx), so the sheet's
 * phone-width geometry is pinned here as the class contract the dev build
 * compiles — flush bottom, rounded top, 85%-of-visual-viewport cap, slide-up
 * — while the drag handle and the flex scroll split are plain CSS/JS and are
 * asserted as real behaviour.
 */

const SheetHarness = ({
  onOpenChange,
}: {
  onOpenChange: (open: boolean) => void;
}) => {
  const [open, setOpen] = useState(true);
  return (
    <AppModalOverlay
      isOpen={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        setOpen(next);
      }}
      className="uu-scope"
    >
      <AppModal className="w-full outline-hidden sm:max-w-md">
        <Dialog
          aria-label="Đổi mật khẩu"
          className="console-form-control flex flex-col gap-3 p-4 outline-hidden"
        >
          <h2 className="text-section-title font-semibold text-primary">
            Đổi mật khẩu
          </h2>
          <p className="text-body-sm text-tertiary">Mật khẩu mới</p>
        </Dialog>
      </AppModal>
    </AppModalOverlay>
  );
};

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 720);
});

describe("AppModal mobile bottom sheet", () => {
  it("ships the sheet posture classes for the phone build and stays a centered modal at sm+", async () => {
    await page.viewport(390, 844);
    const screen = await render(<SheetHarness onOpenChange={() => {}} />);

    const dialog = screen.getByRole("dialog");
    await expect.element(dialog).toBeVisible();

    const overlay = dialog.element().closest(".fixed")!;
    expect(overlay.className).toContain("max-sm:px-0");
    expect(overlay.className).toContain("max-sm:pb-0");

    const sheet = dialog.element().parentElement!;
    expect(sheet.className).toContain("max-sm:flex");
    expect(sheet.className).toContain("max-sm:flex-col");
    expect(sheet.className).toContain("max-sm:rounded-none");
    expect(sheet.className).toContain("max-sm:rounded-t-xl");
    expect(sheet.className).toContain(
      "max-sm:max-h-[calc(var(--visual-viewport-height,100dvh)*0.85)]",
    );
    // Entrance slides up instead of zooming; exit slides back down.
    expect(sheet.className).toContain("max-sm:[--tw-enter-scale:1]");
    expect(sheet.className).toContain("max-sm:slide-in-from-bottom");
    expect(sheet.className).toContain("max-sm:slide-out-to-bottom");
    // The vendored centered geometry stays available for sm+.
    expect(sheet.className).toContain("sm:rounded-2xl");
    expect(sheet.className).toContain("sm:max-w-md");
  });

  it("shows the drag handle only under 640px", async () => {
    await page.viewport(390, 844);
    await render(<SheetHarness onOpenChange={() => {}} />);
    const handle =
      document.body.querySelector<HTMLElement>(".app-sheet-handle");
    expect(handle).toBeInstanceOf(HTMLElement);
    expect(getComputedStyle(handle!).display).toBe("block");
    await cleanup();

    await page.viewport(700, 844);
    await render(<SheetHarness onOpenChange={() => {}} />);
    const hiddenHandle =
      document.body.querySelector<HTMLElement>(".app-sheet-handle");
    expect(hiddenHandle).toBeInstanceOf(HTMLElement);
    expect(getComputedStyle(hiddenHandle!).display).toBe("none");
  });

  it("lets the dialog after the handle take the remaining sheet height", async () => {
    await page.viewport(390, 844);
    const screen = await render(<SheetHarness onOpenChange={() => {}} />);

    const dialog = screen.getByRole("dialog");
    await expect.element(dialog).toBeVisible();

    const style = getComputedStyle(dialog.element());
    expect(style.flexGrow).toBe("1");
    expect(style.minHeight).toBe("0px");
  });

  /** Pointer-event drag across the handle: down, moves, up. */
  const dragHandle = (
    handle: HTMLElement,
    startX: number,
    startY: number,
    dy: number,
  ) => {
    const fire = (type: string, clientY: number) =>
      handle.dispatchEvent(
        new PointerEvent(type, {
          pointerId: 1,
          button: 0,
          clientX: startX,
          clientY,
          bubbles: true,
        }),
      );
    fire("pointerdown", startY);
    fire("pointermove", startY + dy);
    fire("pointerup", startY + dy);
  };

  const handleCenter = (handle: HTMLElement) => {
    const box = handle.getBoundingClientRect();
    return [box.x + box.width / 2, box.y + box.height / 2] as const;
  };

  it("dismisses the sheet when the handle is dragged past the threshold", async () => {
    await page.viewport(390, 844);
    const onOpenChange = vi.fn();
    const screen = await render(<SheetHarness onOpenChange={onOpenChange} />);
    await expect.element(screen.getByRole("dialog")).toBeVisible();

    const handle =
      document.body.querySelector<HTMLElement>(".app-sheet-handle")!;
    const [startX, startY] = handleCenter(handle);

    // Hold past the threshold first: the sheet tracks the pointer 1:1…
    handle.dispatchEvent(
      new PointerEvent("pointerdown", {
        pointerId: 1,
        button: 0,
        clientX: startX,
        clientY: startY,
        bubbles: true,
      }),
    );
    handle.dispatchEvent(
      new PointerEvent("pointermove", {
        pointerId: 1,
        clientX: startX,
        clientY: startY + 200,
        bubbles: true,
      }),
    );
    const sheet = handle.parentElement!;
    expect(sheet.style.transform).toBe("translateY(200px)");

    // …and releasing there dismisses through the overlay's Escape path, so
    // its dismissability guards keep applying.
    handle.dispatchEvent(
      new PointerEvent("pointerup", {
        pointerId: 1,
        clientX: startX,
        clientY: startY + 200,
        bubbles: true,
      }),
    );

    await expect.poll(() => onOpenChange.mock.calls.at(-1)?.[0]).toBe(false);
  });

  it("springs back from a short drag and stays open", async () => {
    await page.viewport(390, 844);
    const onOpenChange = vi.fn();
    const screen = await render(<SheetHarness onOpenChange={onOpenChange} />);
    await expect.element(screen.getByRole("dialog")).toBeVisible();

    const handle =
      document.body.querySelector<HTMLElement>(".app-sheet-handle")!;
    const [startX, startY] = handleCenter(handle);
    dragHandle(handle, startX, startY, 40);

    const sheet = handle.parentElement!;
    // Snapped back with a transition; the sheet did not dismiss.
    expect(sheet.style.transform).toBe("");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    await expect.element(screen.getByRole("dialog")).toBeVisible();
  });
});
