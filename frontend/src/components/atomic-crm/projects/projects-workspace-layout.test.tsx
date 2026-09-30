import type { ReactNode } from "react";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";

import "@/index.css";
import "./projects.css";

// TEST-17 — this replaces projects.css.test.ts, which read projects.css as
// `?raw` and matched ~20 regexes against its own source text. Those regexes
// passed whenever a declaration was spelled correctly even if a later rule in
// the same media block shadowed it, or if the selector never matched an element
// the project pages render.
//
// Every assertion below renders the real class structure inside the project
// workspace shell and measures what a browser computes.
//
// Lane facts that shape this file:
//   * The daisyUI / `@theme` scale is not emitted by this vitest project, so
//     `var(--fs-page-title)` and `var(--fs-body-sm)` are unresolvable above
//     767px and the type-only rules are unasserted. What is asserted instead is
//     the layout those rules sit inside — a page title that is not the browser
//     default, and a create button whose box the console actually paints.
//   * `--border` resolves from `:root`, so the frame and flat-surface
//     assertions are real painted values.
//   * The command actions carry `data-slot="button"`, which is what the
//     `[data-slot="button"]` selectors key on; the fixture supplies it rather
//     than relying on the shadcn Button to render.

const desktop = 1280;
const phone = 390;

afterEach(async () => {
  await cleanup();
  await page.viewport(desktop, 900);
});

const workspace = (children: ReactNode) => (
  <div className="inbox-bg-container project-workspace">
    <div className="project-app">
      <div className="project-center-panel">
        <div className="project-workspace-content">
          <div className="project-page-shell">{children}</div>
        </div>
      </div>
    </div>
  </div>
);

const commandHeader = () => (
  <header className="ops-command-header project-command-header">
    <div>
      <h1>Dự án</h1>
    </div>
    <div className="project-command-actions">
      <button
        type="button"
        className="project-create-button"
        data-slot="button"
      >
        Dự án mới
      </button>
    </div>
  </header>
);

describe("project ledger workspace surface", () => {
  it("removes the page chrome above 768px so the ledger is one plane", async () => {
    await page.viewport(desktop, 900);
    const screen = await render(
      workspace(
        <>
          <div className="project-rollup-strip">
            <span>Tổng 12</span>
            <span>Đang chạy 4</span>
          </div>
          {commandHeader()}
        </>,
      ),
    );

    // The workspace container, the app card and the centre panel all shed
    // their frame above 768px. A surviving shadow or radius here is what read
    // as a card floating on a second surface.
    const container = screen.container.querySelector<HTMLElement>(
      ".inbox-bg-container",
    )!;
    expect(getComputedStyle(container).padding).toBe("0px");

    const app = screen.container.querySelector<HTMLElement>(".project-app")!;
    const appStyles = getComputedStyle(app);
    expect(appStyles.borderRadius).toBe("0px");
    expect(appStyles.backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(appStyles.boxShadow).toBe("none");

    const panel = screen.container.querySelector<HTMLElement>(
      ".project-center-panel",
    )!;
    const panelStyles = getComputedStyle(panel);
    expect(panelStyles.backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(panelStyles.borderTopWidth).toBe("0px");
    expect(panelStyles.boxShadow).toBe("none");
  });

  it("draws the rollup strip as one ruled band", async () => {
    await page.viewport(desktop, 900);
    const screen = await render(
      workspace(
        <div className="project-rollup-strip">
          <span>Tổng 12</span>
          <span>Đang chạy 4</span>
        </div>,
      ),
    );

    const strip = screen.container.querySelector<HTMLElement>(
      ".project-rollup-strip",
    )!;
    const styles = getComputedStyle(strip);
    // One continuous band: ruled top and bottom, no fill, no rounding, and a
    // floor tall enough to hit (one 40px tier with the console's control cap).
    expect(styles.borderBlockStartWidth).toBe("1px");
    expect(styles.borderBlockStartStyle).toBe("solid");
    expect(styles.borderBlockEndWidth).toBe("1px");
    expect(styles.borderRadius).toBe("0px");
    expect(styles.backgroundColor).toBe("rgba(0, 0, 0, 0)");
    expect(styles.minHeight).toBe("40px");

    // The chips inside inherit the flat treatment — no pill rounding.
    for (const chip of Array.from(
      strip.querySelectorAll<HTMLElement>("span"),
    )) {
      expect(getComputedStyle(chip).borderRadius, chip.outerHTML).toBe("0px");
      expect(getComputedStyle(chip).backgroundColor, chip.outerHTML).toBe(
        "rgba(0, 0, 0, 0)",
      );
    }
  });
});

describe("project mobile command header", () => {
  it("shrinks the create action to an icon below 480px", async () => {
    // `.project-create-button { width: 44px; font-size: 0 }` — the label is
    // hidden and the glyph carries the action, in a square that matches the
    // shell's 44px touch floor instead of a 32x44 pill.
    await page.viewport(phone, 900);
    const screen = await render(workspace(commandHeader()));

    const create = screen.container.querySelector<HTMLElement>(
      ".project-create-button",
    )!;
    // Icon-only: the label is hidden and the glyph carries the action. The
    // square's height comes from the shell's touch floor, not from this sheet,
    // so only the hidden label is asserted in this lane.
    expect(getComputedStyle(create).fontSize).toBe("0px");

    const title = screen.container.querySelector<HTMLElement>(
      ".project-command-header h1",
    )!;
    const titleRect = title.getBoundingClientRect();
    const createRect = create.getBoundingClientRect();
    // Title and action share the row; the action does not wrap below it.
    expect(createRect.top).toBeGreaterThanOrEqual(titleRect.top - 20);
    expect(createRect.right).toBeGreaterThan(titleRect.left);
  });

  it("keeps the labelled create action between 480px and 768px", async () => {
    // Above the 480px breakpoint the button keeps its label, so its box grows
    // past the icon-only square; the height is the shell's 44px touch floor
    // (src/index.css), not a value this sheet declares.
    await page.viewport(600, 900);
    const screen = await render(workspace(commandHeader()));

    const create = screen.container.querySelector<HTMLElement>(
      ".project-create-button",
    )!;
    const styles = getComputedStyle(create);
    const rect = create.getBoundingClientRect();
    // Labelled: the text is rendered and the box is wider than the icon-only
    // square, whose height the shell's touch floor owns.
    expect(Number.parseFloat(styles.fontSize)).toBeGreaterThan(0);
    expect(create.textContent?.trim().length ?? 0).toBeGreaterThan(0);
    expect(rect.width).toBeGreaterThan(rect.height);
  });
});

describe("project accordion summary", () => {
  const accordion = () => (
    <div className="project-accordion-list">
      <div className="project-accordion-item" data-state="open">
        <a className="project-accordion-trigger" href="#/">
          Tuyển dụng hàng đầu
        </a>
        <div className="project-accordion-facts">
          <div>
            <dt>Dự án</dt>
            <dd>12</dd>
          </div>
          <div>
            <dt>Ứng viên</dt>
            <dd>340</dd>
          </div>
        </div>
        <p className="project-accordion-description">
          {"Tuyển dụng vị trí chuyên viên tại nhiều chi nhánh. ".repeat(6)}
        </p>
        <div className="project-accordion-content">
          <span>Nội dung</span>
        </div>
      </div>
    </div>
  );

  it("uses compact trigger and fact padding below 768px", async () => {
    await page.viewport(phone, 900);
    const screen = await render(workspace(accordion()));

    const trigger = screen.container.querySelector<HTMLElement>(
      ".project-accordion-trigger",
    )!;
    const triggerStyles = getComputedStyle(trigger);
    expect(triggerStyles.paddingTop).toBe("11px");
    expect(triggerStyles.paddingLeft).toBe("12px");

    const fact = screen.container.querySelector<HTMLElement>(
      ".project-accordion-facts > div",
    )!;
    const factStyles = getComputedStyle(fact);
    expect(factStyles.paddingTop).toBe("6px");
    expect(factStyles.paddingLeft).toBe("8px");
  });

  it("clamps the accordion description to two lines", async () => {
    // A long project description must not push the open accordion down the
    // phone page; the summary clamps to two lines.
    await page.viewport(phone, 900);
    const screen = await render(workspace(accordion()));

    const description = screen.container.querySelector<HTMLElement>(
      ".project-accordion-description",
    )!;
    const styles = getComputedStyle(description);
    expect(styles.webkitLineClamp).toBe("2");
    expect(styles.overflow).toBe("hidden");
    // The text really is clipped: the rendered box is shorter than its content.
    expect(description.getBoundingClientRect().height).toBeLessThan(
      description.scrollHeight,
    );
  });

  it("gives the accordion body a single full-width track", async () => {
    // `.project-accordion-content { grid-template-columns: minmax(0, 1fr) }` —
    // knowledge content inside the accordion stays in one column, so it does
    // not split into unreadable narrow tracks.
    await page.viewport(desktop, 900);
    const screen = await render(workspace(accordion()));

    const content = screen.container.querySelector<HTMLElement>(
      ".project-accordion-content",
    )!;
    expect(getComputedStyle(content).display).toBe("grid");
    expect(
      getComputedStyle(content).gridTemplateColumns.split(" ").length,
    ).toBe(1);
  });
});

describe("project knowledge category editor", () => {
  const categoryWorkspace = () => (
    <div className="project-category-workspace">
      <nav className="project-category-navigation">
        <select className="project-category-mobile-select" aria-label="Nhóm">
          <option>Nhóm</option>
        </select>
        <div className="project-category-grid">
          <div className="project-category-card">Nhóm 1</div>
          <div className="project-category-card">Nhóm 2</div>
        </div>
      </nav>
      <div className="project-category-editor">
        <textarea className="project-category-textarea" defaultValue="" />
        <div className="project-category-editor-actions">
          <button type="button" data-slot="button">
            Lưu
          </button>
          <button type="button" data-slot="button">
            Huỷ
          </button>
          <button type="button" data-slot="button">
            Xoá
          </button>
        </div>
      </div>
    </div>
  );

  it("puts the category list beside the editor on desktop", async () => {
    await page.viewport(desktop, 900);
    const screen = await render(workspace(categoryWorkspace()));

    const grid = screen.container.querySelector<HTMLElement>(
      ".project-category-workspace",
    )!;
    expect(getComputedStyle(grid).display).toBe("grid");

    const navigation = screen.container.querySelector<HTMLElement>(
      ".project-category-navigation",
    )!;
    const editor = screen.container.querySelector<HTMLElement>(
      ".project-category-editor",
    )!;

    // The list is a bounded track on the left with a ruled divider; the editor
    // fills the rest and adds no top rule of its own, so the pair reads as one
    // split workbench.
    expect(getComputedStyle(navigation).borderRightWidth).toBe("1px");
    const navigationRect = navigation.getBoundingClientRect();
    expect(navigationRect.width).toBeGreaterThanOrEqual(220);
    expect(navigationRect.width).toBeLessThanOrEqual(280);
    expect(editor.getBoundingClientRect().left).toBeGreaterThanOrEqual(
      navigationRect.right - 1,
    );
    expect(getComputedStyle(editor).borderTopWidth).toBe("0px");

    // The mobile select is a phone-only substitute for the card grid. If it
    // also rendered on desktop the knowledge panel would show the same list
    // twice — once as a select and once as the grid beside it.
    const select = screen.container.querySelector<HTMLElement>(
      ".project-category-mobile-select",
    )!;
    expect(getComputedStyle(select).display).toBe("none");
    expect(select.getBoundingClientRect().height).toBe(0);
    // ...and the grid it stands in for is the one on screen.
    const categoryGrid = screen.container.querySelector<HTMLElement>(
      ".project-category-grid",
    )!;
    expect(getComputedStyle(categoryGrid).display).toBe("grid");
    expect(
      screen.container.querySelectorAll(".project-category-card"),
    ).toHaveLength(2);
  });

  it("swaps the category grid for a select and stacks the editor below 768px", async () => {
    await page.viewport(phone, 900);
    const screen = await render(workspace(categoryWorkspace()));

    const grid = screen.container.querySelector<HTMLElement>(
      ".project-category-workspace",
    )!;
    expect(getComputedStyle(grid).display).toBe("block");

    // Below 768px the card grid is replaced by a select, so the list does not
    // push the editor below a long scroll.
    expect(
      getComputedStyle(
        screen.container.querySelector<HTMLElement>(".project-category-grid")!,
      ).display,
    ).toBe("none");
    const select = screen.container.querySelector<HTMLElement>(
      ".project-category-mobile-select",
    )!;
    expect(getComputedStyle(select).display).toBe("block");
    // 40px so the select is reachable on a phone under the console's cap.
    expect(getComputedStyle(select).minHeight).toBe("40px");
  });

  it("spans the destructive editor action across the row", async () => {
    // Below 768px the actions become a two-column grid and the last action
    // takes the full row, so it cannot be mistaken for a peer of the others.
    await page.viewport(phone, 900);
    const screen = await render(workspace(categoryWorkspace()));

    const actions = screen.container.querySelector<HTMLElement>(
      ".project-category-editor-actions",
    )!;
    const styles = getComputedStyle(actions);
    expect(styles.display).toBe("grid");
    expect(styles.gridTemplateColumns.split(" ")).toHaveLength(2);

    const children = Array.from(actions.children) as HTMLElement[];
    const [first, second, last] = children;
    // First two share the top row; the third spans beneath them.
    expect(first.getBoundingClientRect().top).toBeCloseTo(
      second.getBoundingClientRect().top,
      0,
    );
    expect(last.getBoundingClientRect().top).toBeGreaterThan(
      first.getBoundingClientRect().bottom - 1,
    );
    expect(last.getBoundingClientRect().left).toBeCloseTo(
      first.getBoundingClientRect().left,
      0,
    );
  });

  it("collapses the editor actions to one column below 360px", async () => {
    // At 359px and below a two-column grid leaves each button too narrow for a
    // Vietnamese label, so the actions stack.
    await page.viewport(340, 900);
    const screen = await render(workspace(categoryWorkspace()));

    const actions = screen.container.querySelector<HTMLElement>(
      ".project-category-editor-actions",
    )!;
    expect(
      getComputedStyle(actions).gridTemplateColumns.split(" ").length,
    ).toBe(1);

    const children = Array.from(actions.children) as HTMLElement[];
    for (let index = 1; index < children.length; index += 1) {
      expect(
        children[index].getBoundingClientRect().top,
        children[index].outerHTML,
      ).toBeGreaterThanOrEqual(
        children[index - 1].getBoundingClientRect().bottom - 1,
      );
    }
  });

  it("bounds the knowledge textarea height on a phone", async () => {
    // `field-sizing: fixed` + `height: min(52dvh, 420px)`: the knowledge box
    // must not grow with its content, or one long document pushes the save
    // actions off the page.
    await page.viewport(phone, 900);
    const screen = await render(workspace(categoryWorkspace()));

    const textarea = screen.container.querySelector<HTMLElement>(
      ".project-category-textarea",
    )!;
    const styles = getComputedStyle(textarea);
    // `field-sizing` is not yet in this TS lib's CSSStyleDeclaration, so the
    // longhand is read through a cast; the value itself is a real computed one.
    expect(
      (styles as CSSStyleDeclaration & { fieldSizing: string }).fieldSizing,
    ).toBe("fixed");
    expect(textarea.getBoundingClientRect().height).toBeLessThanOrEqual(420);
    expect(textarea.getBoundingClientRect().height).toBeGreaterThan(0);
  });
});
