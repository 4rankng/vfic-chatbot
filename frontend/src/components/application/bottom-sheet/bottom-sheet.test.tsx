import { cleanup, render } from "vitest-browser-react";
import { userEvent } from "vitest/browser";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BottomSheet } from "./bottom-sheet";

afterEach(async () => {
  await cleanup();
});

const renderSheet = async (onOpenChange = vi.fn()) => {
  const screen = await render(
    <BottomSheet
      isOpen
      onOpenChange={onOpenChange}
      title="Bản ghi cuộc gọi của 0362698948"
      header={<div className="transcripts-sheet-header">đầu sheet</div>}
    >
      <p>nội dung</p>
    </BottomSheet>,
  );
  const dialog = screen.getByRole("dialog");
  await expect.element(dialog).toBeVisible();
  const sheet = dialog.element().parentElement as HTMLElement;
  return { screen, dialog, sheet, onOpenChange };
};

const dragGripBy = (dialog: { element: () => Element }, deltaY: number) => {
  const grip = dialog
    .element()
    .querySelector<HTMLElement>(".bottom-sheet-handle")!;
  grip.dispatchEvent(
    new PointerEvent("pointerdown", {
      bubbles: true,
      clientY: 700,
      pointerId: 3,
      pointerType: "touch",
    }),
  );
  grip.dispatchEvent(
    new PointerEvent("pointermove", {
      bubbles: true,
      clientY: 700 - deltaY,
      pointerId: 3,
      pointerType: "touch",
    }),
  );
  grip.dispatchEvent(
    new PointerEvent("pointerup", {
      bubbles: true,
      clientY: 700 - deltaY,
      pointerId: 3,
      pointerType: "touch",
    }),
  );
};

describe("BottomSheet", () => {
  it("is a named modal dialog at the 50% detent with grip and 40% scrim", async () => {
    const { dialog, sheet } = await renderSheet();

    expect(dialog.element().getAttribute("aria-modal")).toBe("true");
    expect(sheet.style.height).toContain("0.5");
    // 32×4 gray-300 grip, 40% scrim — the consult's §3 tokens.
    expect(
      dialog
        .element()
        .querySelector(".bottom-sheet-handle .h-1.w-8.bg-neutral-300"),
    ).not.toBeNull();
    expect(sheet.parentElement?.className).toContain("bg-black/40");
  });

  it("drags up to the 90% detent and back down to 50%", async () => {
    const { dialog, sheet } = await renderSheet();

    dragGripBy(dialog, 300);
    await expect.poll(() => sheet.style.height).toContain("0.9");

    dragGripBy(dialog, -400);
    await expect.poll(() => sheet.style.height).toContain("0.5");
  });

  it("dismisses through Escape", async () => {
    const { onOpenChange } = await renderSheet();

    await userEvent.keyboard("{Escape}");
    await expect.poll(() => onOpenChange.mock.calls).toContainEqual([false]);
  });
});
