import { cleanup, render } from "vitest-browser-react";
import { expect, it, vi, describe, afterEach } from "vitest";

import { Tooltip, TooltipTrigger } from "./tooltip";

// CHAT-19 (2026-10-29): on touch there is no hover-out, so an opened tooltip
// pinned its pill over the row content until the next tap (the Users "Sửa …"
// pill covered the status chip of its own row). These tests pin the contract
// on the shared tooltip so every ButtonUtility benefits: on coarse pointers
// the pill closes itself shortly after opening, while mouse desktops keep the
// hover-tooltip behaviour unchanged. The pill unmounts on close, so the
// assertions read the DOM text rather than an element locator.

const TOUCH_AUTO_CLOSE_MS = 2000;
const TITLE = "Sửa Nguyễn Văn Admin";
const pillIsOpen = () => (document.body.textContent ?? "").includes(TITLE);

// Test seam: a matchMedia stub is the only way to simulate a touch device in
// the browser test project (the tooltip keys its auto-close on
// `(pointer: coarse)`).
const stubPointer = (coarse: boolean) =>
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        matches: query.includes("pointer: coarse") ? coarse : false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as MediaQueryList,
  );

// Test seam: open the tooltip through react-aria's focus-visible path — a
// keydown primes the interaction modality to 'keyboard', after which focusing
// the trigger opens the tooltip deterministically (hover synthesis fights
// useHover's emulated-pointer guards in a synthetic test bed).
const focusOpen = (trigger: HTMLElement | SVGElement) => {
  document.dispatchEvent(
    new KeyboardEvent("keydown", { bubbles: true, key: "Tab" }),
  );
  trigger.focus();
};

describe("tooltip touch behaviour", () => {
  afterEach(async () => {
    vi.restoreAllMocks();
    await cleanup();
  });

  it("auto-closes on coarse pointers so the pill never lingers over row content", async () => {
    stubPointer(true);
    const screen = await render(
      <Tooltip title={TITLE} delay={0}>
        <TooltipTrigger aria-label={TITLE}>Sửa</TooltipTrigger>
      </Tooltip>,
    );

    const trigger = screen.getByRole("button", { name: TITLE }).element();
    focusOpen(trigger);
    await vi.waitFor(() => expect(pillIsOpen()).toBe(true));

    await vi.waitFor(() => expect(pillIsOpen()).toBe(false), {
      timeout: TOUCH_AUTO_CLOSE_MS + 1500,
    });
  });

  it("keeps the hover tooltip open on fine pointers (desktop unchanged)", async () => {
    stubPointer(false);
    const screen = await render(
      <Tooltip title={TITLE} delay={0}>
        <TooltipTrigger aria-label={TITLE}>Sửa</TooltipTrigger>
      </Tooltip>,
    );

    const trigger = screen.getByRole("button", { name: TITLE }).element();
    focusOpen(trigger);
    await vi.waitFor(() => expect(pillIsOpen()).toBe(true));

    // The tsconfig lib target predates Promise.withResolvers (es2024), so the
    // executor form is the build-compatible wait here.
    await new Promise<void>((resolve) => {
      setTimeout(resolve, TOUCH_AUTO_CLOSE_MS + 400);
    });
    expect(pillIsOpen()).toBe(true);
  });
});
