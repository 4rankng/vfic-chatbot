import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";

import "@/index.css";
// `../inbox.css` is the barrel the console loads, and it fixes the cascade
// order: personas-studio.css lands *before* personas-responsive.css, so the
// ≤760px overrides in the responsive section win. Importing the two files
// directly in a different order silently inverts which rule applies.
import "../inbox.css";

// TEST-17 — this replaces responsive-visual-regressions.test.ts, which read
// features.css and personas-responsive.css as `?raw` and matched four regexes
// against them. Those pins could not see whether a media query still applied at
// a real viewport, or whether the element a rule targets is the one the console
// renders.
//
// Everything below renders the real class structure inside the shells the
// console uses and measures what a browser computes at the widths that matter.
//
// Lane facts that shape this file:
//   * The daisyUI / `@theme` scale is not emitted by this vitest project, so
//     `var(--fs-page-title)` and `var(--crm-fs-title-lg)` are unresolvable above
//     767px. The knowledge title's *desktop* font size is therefore asserted
//     only below 768px, where `--text-page-title: 1.375rem` is set directly on
//     `:root` and resolves to 22px. The mobile title block that overrides it is
//     asserted at phone width, where `--crm-fs-title-lg` also resolves.
//   * `page.viewport()` drops `:root` custom properties, so every token here is
//     read off the rendered element via `getComputedStyle(element)`, never off
//     `documentElement`.

const wide = 1280;
const tablet = 800;
const phone = 390;

afterEach(async () => {
  await cleanup();
  await page.viewport(wide, 900);
});

describe("knowledge workspace title", () => {
  it("keeps the knowledge title on the shared page-title scale", async () => {
    // `.knowledge-command-header h1 { font-size: var(--fs-page-title) }`. The
    // token only resolves below 768px in this lane, so that is where the size is
    // measured; above it the rule is unasserted rather than pinned to the
    // browser's 16px default, which is a different failure.
    await page.viewport(760, 900);
    const screen = await render(
      <div className="inbox-bg-container">
        <div className="knowledge-page-shell">
          <header className="knowledge-command-header">
            <div>
              <p className="ops-kicker">Kiến thức</p>
              <h1>Kiến thức</h1>
              <p>Nguồn và đơn vị kiến thức.</p>
            </div>
          </header>
        </div>
      </div>,
    );

    const title = screen.container.querySelector<HTMLElement>(
      ".knowledge-command-header h1",
    )!;
    // 22px is `--text-page-title` below 768px — not the 16px body default, and
    // not the 32px `h1` browser default.
    expect(getComputedStyle(title).fontSize).toBe("22px");
  });

  it("stacks the knowledge header at tablet width and sizes the phone title", async () => {
    // Two separate overrides, asserted at the widths they actually apply to.
    // features.css 768–900px stacks the header so the actions sit under the
    // title instead of squeezing it; personas-responsive.css ≤760px pins the
    // title to `--crm-fs-title-lg` with a 2px top margin.
    const header = () => (
      <header className="knowledge-command-header">
        <div>
          <p className="ops-kicker">Kiến thức</p>
          <h1>Kiến thức</h1>
          <p>Nguồn và đơn vị kiến thức.</p>
        </div>
        <div className="knowledge-command-actions">
          <button type="button">Thêm</button>
        </div>
      </header>
    );

    await page.viewport(tablet, 900);
    const tabletScreen = await render(
      <div className="inbox-bg-container">
        <div className="knowledge-page-shell">
          {header()}
        </div>
      </div>,
    );
    const tabletHeader = tabletScreen.container.querySelector<HTMLElement>(
      ".knowledge-command-header",
    )!;
    expect(getComputedStyle(tabletHeader).flexDirection).toBe("column");
    expect(getComputedStyle(tabletHeader).alignItems).toBe("flex-start");

    await cleanup();
    await page.viewport(phone, 900);
    const phoneScreen = await render(
      <div className="inbox-bg-container">
        <div className="knowledge-page-shell">
          {header()}
        </div>
      </div>,
    );
    const title = phoneScreen.container.querySelector<HTMLElement>(
      ".knowledge-command-header h1",
    )!;
    expect(getComputedStyle(title).fontSize).toBe("22px");
    expect(getComputedStyle(title).marginTop).toBe("2px");
  });
});

describe("knowledge unit disclosure", () => {
  const disclosure = () => (
    <div className="inbox-bg-container">
      <div className="knowledge-page-shell">
        <div className="knowledge-unit-list">
          <details className="knowledge-unit-disclosure">
            <summary>
              <span className="knowledge-unit-summary-copy">Đơn vị tuyển dụng</span>
              <span className="knowledge-unit-chevron" aria-hidden="true">
                ▾
              </span>
            </summary>
            <div className="knowledge-unit-body">
              <p>Nội dung đơn vị.</p>
            </div>
          </details>
        </div>
      </div>
    </div>
  );

  it("keeps a disclosure row tall enough to tap", async () => {
    // 68px on desktop, 72px at ≤760px: the summary is the only tap target for
    // a whole knowledge unit, and a text-height row was untappable.
    await page.viewport(wide, 900);
    const wideScreen = await render(disclosure());
    const wideSummary = wideScreen.container.querySelector<HTMLElement>(
      ".knowledge-unit-disclosure > summary",
    )!;
    expect(getComputedStyle(wideSummary).minHeight).toBe("68px");
    expect(wideSummary.getBoundingClientRect().height).toBeGreaterThanOrEqual(
      68,
    );

    await cleanup();
    await page.viewport(phone, 900);
    const phoneScreen = await render(disclosure());
    const phoneSummary = phoneScreen.container.querySelector<HTMLElement>(
      ".knowledge-unit-disclosure > summary",
    )!;
    expect(getComputedStyle(phoneSummary).minHeight).toBe("72px");
    // The chevron track narrows on a phone to leave the label the room.
    expect(getComputedStyle(phoneSummary).gridTemplateColumns.split(" ")).toHaveLength(
      2,
    );
    expect(phoneSummary.getBoundingClientRect().height).toBeGreaterThanOrEqual(
      72,
    );
  });

  it("rotates the chevron only while the disclosure is open", async () => {
    // `.knowledge-unit-disclosure[open] .knowledge-unit-chevron` rotates 180°.
    // Pinned behaviourally: the transform appears on open and is gone on close,
    // so a selector that stopped matching the `[open]` state goes red.
    await page.viewport(wide, 900);
    const screen = await render(disclosure());

    const details = screen.container.querySelector<HTMLDetailsElement>(
      "details.knowledge-unit-disclosure",
    )!;
    const summary = screen.container.querySelector<HTMLElement>("summary")!;
    const chevron = screen.container.querySelector<HTMLElement>(
      ".knowledge-unit-chevron",
    )!;

    expect(details.open).toBe(false);
    expect(getComputedStyle(chevron).transform).toBe("none");

    await page.elementLocator(summary).click();
    await expect.poll(() => details.open).toBe(true);
    // `rotate(180deg)` is a 180° rotation about Z; the browser reports it as
    // the matrix (-1, 0, 0, -1, 0, 0) once the 180ms transition settles.
    await expect
      .poll(() => getComputedStyle(chevron).transform, { timeout: 3000 })
      .toBe("matrix(-1, 0, 0, -1, 0, 0)");

    await page.elementLocator(summary).click();
    await expect.poll(() => details.open).toBe(false);
    await expect
      .poll(() => getComputedStyle(chevron).transform, { timeout: 3000 })
      .toBe("none");
  });
});

describe("knowledge page shell width", () => {
  it("never lets the knowledge shell overflow a phone viewport", async () => {
    // Below 760px the shell and its children are pinned to
    // `width: 100%; min-width: 0; max-width: 100%`. A long Vietnamese label
    // used to push the whole page sideways.
    await page.viewport(phone, 900);
    const screen = await render(
      <div className="inbox-bg-container">
        <div className="knowledge-page-shell">
          <header className="knowledge-command-header">
            <div>
              <h1>Kiến thức tuyển dụng và vận hành</h1>
            </div>
          </header>
          <div className="knowledge-status-strip">trạng thái</div>
          <div className="knowledge-source-workspace">
            <nav className="knowledge-source-navigation">nguồn</nav>
            <div className="knowledge-source-detail">chi tiết</div>
          </div>
        </div>
      </div>,
    );

    const shell = screen.container.querySelector<HTMLElement>(
      ".knowledge-page-shell",
    )!;
    const styles = getComputedStyle(shell);
    expect(styles.minWidth).toBe("0px");
    expect(styles.maxWidth).toBe("100%");

    // The real proof: nothing inside overflows the phone viewport, and the
    // document has no horizontal scroll.
    const shellRect = shell.getBoundingClientRect();
    for (const child of Array.from(shell.children)) {
      expect(
        child.getBoundingClientRect().right,
        (child as HTMLElement).className,
      ).toBeLessThanOrEqual(shellRect.right + 1);
    }
    expect(
      document.scrollingElement!.scrollWidth,
    ).toBeLessThanOrEqual(document.scrollingElement!.clientWidth + 1);
  });
});

describe("settings destination navigation", () => {
  const sideNav = (count: number) => (
    <div className="inbox-bg-container settings-workspace">
      <div className="settings-workspace-content">
        <nav>
          <div className="settings-side-nav-list">
            {Array.from({ length: count }, (_, index) => (
              <a
                key={index}
                className="settings-side-nav-link"
                href="#/"
              >
                Mục {index + 1}
              </a>
            ))}
          </div>
        </nav>
      </div>
    </div>
  );

  it("puts every settings destination in a tablet grid between 768 and 900px", async () => {
    // Six destinations would be a single unreadable column on a tablet, and a
    // three-column grid keeps them all on screen at once.
    await page.viewport(tablet, 900);
    const screen = await render(sideNav(6));

    const list = screen.container.querySelector<HTMLElement>(
      ".settings-side-nav-list",
    )!;
    const tracks = getComputedStyle(list).gridTemplateColumns.split(" ");

    expect(tracks).toHaveLength(3);
    const links = Array.from(
      screen.container.querySelectorAll<HTMLElement>(
        ".settings-side-nav-link",
      ),
    );
    expect(links).toHaveLength(6);
    // Three equal columns over two rows.
    const rects = links.map((link) => link.getBoundingClientRect());
    for (let index = 3; index < rects.length; index += 1) {
      expect(rects[index].width).toBeCloseTo(rects[0].width, 0);
    }
    expect(rects[3].top).toBeGreaterThanOrEqual(rects[0].bottom - 1);
    expect(rects[0].left).toBeLessThan(rects[1].left);
    expect(rects[1].left).toBeLessThan(rects[2].left);
  });

  it("keeps the tablet grid out of the desktop and phone layouts", async () => {
    // The grid is scoped to 768–900px. Above it the destinations stack in the
    // sidebar; below it they become a horizontal scroller.
    await page.viewport(wide, 900);
    const wideScreen = await render(sideNav(6));
    expect(
      getComputedStyle(
        wideScreen.container.querySelector<HTMLElement>(
          ".settings-side-nav-list",
        )!,
      ).gridTemplateColumns.split(" ").length,
    ).toBe(1);

    await cleanup();
    await page.viewport(phone, 900);
    const phoneScreen = await render(sideNav(6));
    const phoneList = phoneScreen.container.querySelector<HTMLElement>(
      ".settings-side-nav-list",
    )!;
    // Below 768px the tablet grid is replaced by a horizontal scroller: column
    // flow with equal `minmax(168px, 1fr)` auto tracks, so all six destinations
    // share one swipeable row instead of wrapping into a three-column grid that
    // no longer fits.
    const phoneStyles = getComputedStyle(phoneList);
    expect(phoneStyles.gridAutoFlow).toBe("column");
    expect(phoneStyles.overflowX).toBe("auto");
    expect(phoneStyles.gridTemplateColumns.split(" ")).toHaveLength(6);
    // The scroller keeps a 168px floor per destination.
    for (const link of Array.from(
      phoneScreen.container.querySelectorAll<HTMLElement>(
        ".settings-side-nav-link",
      ),
    )) {
      expect(
        link.getBoundingClientRect().width,
        link.outerHTML,
      ).toBeGreaterThanOrEqual(168);
    }
  });
});

describe("Agent scope and activity columns", () => {
  it("stacks the two columns instead of squeezing them on a phone", async () => {
    // Below 760px `.persona-scope-activity-grid` drops to one track. The scope
    // and activity panels share the row above that, where both are readable.
    const grid = () => (
      <div className="inbox-bg-container">
        <div className="persona-workspace-content">
          <div className="persona-scope-activity-grid">
            <div className="persona-scope-row">Phạm vi kênh</div>
            <div className="persona-scope-activity">Hoạt động</div>
          </div>
        </div>
      </div>
    );

    await page.viewport(phone, 900);
    const phoneScreen = await render(grid());
    const phoneColumns = Array.from(
      phoneScreen.container.querySelectorAll<HTMLElement>(
        ".persona-scope-activity-grid > *",
      ),
    );
    expect(phoneColumns).toHaveLength(2);
    expect(phoneColumns[1].getBoundingClientRect().top).toBeGreaterThanOrEqual(
      phoneColumns[0].getBoundingClientRect().bottom - 1,
    );

    await cleanup();
    await page.viewport(wide, 900);
    const wideScreen = await render(grid());
    const wideColumns = Array.from(
      wideScreen.container.querySelectorAll<HTMLElement>(
        ".persona-scope-activity-grid > *",
      ),
    );
    // Two tracks side by side, each wide enough for its own label.
    expect(wideColumns[1].getBoundingClientRect().left).toBeGreaterThan(
      wideColumns[0].getBoundingClientRect().right - 1,
    );
    expect(wideColumns[0].getBoundingClientRect().width).toBeGreaterThan(100);
  });
});
