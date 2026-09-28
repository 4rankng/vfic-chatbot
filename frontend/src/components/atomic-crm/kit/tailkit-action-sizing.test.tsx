import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";

import "@/index.css";
import "./tailkit-system.css";

// TEST-17 — this replaces tailkit-system.css.test.ts, which asserted the
// stylesheet's own source text. Those regexes passed whenever the rule was
// spelled correctly, even when a later declaration shadowed it or the element it
// targets is never rendered. Everything below is a measured value on a rendered
// control inside the real `.tailkit-workspace-content` shell.
//
// The typography scale lives in an `@theme` block, which this lane does not
// expand, so the fixture supplies `--fs-body-sm` (13px, the value
// `--text-body-sm` resolves to) and the assertion proves the *rule* consumes
// that token — a dropped `font-size` declaration falls back to the 16px browser
// default and goes red. This is the same technique mobile-workspace.test.tsx
// uses for its cascade fixture.

const desktop = 1280;

afterEach(async () => {
  await cleanup();
  await page.viewport(desktop, 720);
});

const heightOf = (element: Element) => getComputedStyle(element).height;

const actionShell = (children: React.ReactNode) => (
  <div
    className="tailkit-workspace-content"
    style={{ "--fs-body-sm": "13px" } as React.CSSProperties}
  >
    {children}
  </div>
);

describe("Tailkit action sizing system", () => {
  it("keeps one compact desktop hierarchy for text actions", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(
      actionShell(
        <>
          <button type="button" className="tt-btn">
            Thường
          </button>
          <button type="button" className="tt-btn tt-btn-sm">
            Nhỏ
          </button>
          <button type="button" className="tt-btn tt-btn-lg">
            Lớn
          </button>
        </>,
      ),
    );

    const [normal, small, large] = Array.from(
      screen.container.querySelectorAll<HTMLElement>("button"),
    );

    // 28/32/36px text actions (was: `--tt-size: 1.75rem/2rem/2.25rem` in source).
    expect(heightOf(small)).toBe("28px");
    expect(heightOf(normal)).toBe("32px");
    expect(heightOf(large)).toBe("36px");
    // `height` and `min-height` are pinned together, so a control that grows
    // content (a two-line label) still keeps its 32px floor.
    for (const button of [small, normal, large]) {
      expect(heightOf(button), button.outerHTML).toBe(
        getComputedStyle(button).minHeight,
      );
    }
  });

  it("labels every text action at the small body size and semibold weight", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(
      actionShell(
        <>
          <button type="button" className="tt-btn tt-btn-sm">
            Nhỏ
          </button>
          <button type="button" className="tt-btn tt-btn-lg">
            Lớn
          </button>
        </>,
      ),
    );

    for (const button of screen.container.querySelectorAll<HTMLElement>(
      "button",
    )) {
      const styles = getComputedStyle(button);
      expect(styles.fontSize, button.outerHTML).toBe("13px");
      expect(styles.fontWeight, button.outerHTML).toBe("600");
    }
  });

  it("does not apply text-action sizing to square, circular, or touch controls", async () => {
    // The desktop rule excludes `.tt-btn-square`, `.tt-btn-circle`, and
    // `.tt-btn-touch`; an icon-only square that inherited 32px would clip its
    // glyph, and a touch control that inherited 32px would lose its 44px target.
    await page.viewport(desktop, 720);

    const screen = await render(
      actionShell(
        <>
          <button type="button" className="tt-btn tt-btn-square">
            S
          </button>
          <button type="button" className="tt-btn tt-btn-circle">
            C
          </button>
          <button type="button" className="tt-btn tt-btn-touch">
            Chạm
          </button>
        </>,
      ),
    );

    const [square, circle, touch] = Array.from(
      screen.container.querySelectorAll<HTMLElement>("button"),
    );

    expect(heightOf(square)).not.toBe("32px");
    expect(heightOf(circle)).not.toBe("32px");
    expect(heightOf(touch)).not.toBe("32px");
  });

  it("does not collapse conversation data rows to the action-button height", async () => {
    // `.conversation` marks a chat-row action; it keeps its own geometry.
    await page.viewport(desktop, 720);

    const screen = await render(
      actionShell(
        <>
          <button type="button" className="tt-btn tt-btn-sm conversation">
            Tin nhắn
          </button>
          <button type="button" className="tt-btn tt-btn-sm">
            Hành động
          </button>
        </>,
      ),
    );

    const [row, action] = Array.from(
      screen.container.querySelectorAll<HTMLElement>("button"),
    );

    expect(heightOf(action)).toBe("28px");
    expect(heightOf(row)).not.toBe("28px");
  });

  it("restores 44px touch targets for every control at phone widths", async () => {
    await page.viewport(767, 900);

    const screen = await render(
      actionShell(
        <>
          <button type="button" className="tt-btn">
            Nút
          </button>
          {/* `a[role="button"]` only gets a box once the anchor is laid out as
              one; the rule sets min-height, which an inline box ignores. */}
          <a role="button" href="#/" style={{ display: "inline-block" }}>
            Liên kết
          </a>
          <input type="text" />
          <select defaultValue="">
            <option value="">Chọn</option>
          </select>
        </>,
      ),
    );

    const controls = Array.from(
      screen.container.querySelectorAll<HTMLElement>(
        "button, a, input, select",
      ),
    );
    expect(controls).toHaveLength(4);

    for (const control of controls) {
      const styles = getComputedStyle(control);
      expect(styles.minHeight, control.outerHTML).toBe("44px");
      // The declared floor must survive a control whose content is smaller than
      // the target — a `min-height` silently downgraded to `height` keeps the
      // computed value but breaks the box the finger has to hit.
      expect(
        control.getBoundingClientRect().height,
        control.outerHTML,
      ).toBeGreaterThanOrEqual(44);
    }
  });
});
