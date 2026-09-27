import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";

import "../conversations/inbox.css";
import "@/index.css";

// TEST-17 — this replaces knowledge-workspace-layout.test.ts, which asserted
// regexes against features.css / personas-responsive.css and `?raw` TSX sources.
// A regex passes when the rule is spelled correctly but shadowed, or applied to
// an element the page never renders. Everything below is measured on a rendered
// workspace at the breakpoint the rule is scoped to.
//
// The two source pins this file used to carry — "the source subpages do not
// import @/components/ui/card" and "KnowledgeSourceShow renders
// KnowledgeDetailPanel" — are enforced behaviourally by the sibling
// KnowledgeSourceSubpages.test.tsx, which renders both subpages and asserts
// `querySelector("[data-slot='card']")` is null and that the panel's
// `data-heading-as` marker is present.

const desktop = 1280;
const phone = 390;

afterEach(async () => {
  await cleanup();
  await page.viewport(desktop, 720);
});

const sourceWorkspace = (children: React.ReactNode) => (
  <div className="knowledge-page-shell">
    <div className="knowledge-source-workspace">
      <nav className="knowledge-source-navigation">
        <div className="knowledge-source-navigation-header">
          <span>Nguồn</span>
          <button type="button">Thêm nguồn</button>
        </div>
        {/* `flex-wrap`/`justify-content` on the pagination row only mean anything
            on a flex container, which is what ra's <Pagination> renders; its
            first child (the per-page select) is hidden by the stylesheet, so the
            fixture reproduces that too. */}
        <ul className="knowledge-source-pagination" style={{ display: "flex" }}>
          <li className="knowledge-source-pagination-per-page">10 / trang</li>
          <li>
            {/* shadcn's PaginationLink gives the anchor its `inline-flex` box;
                Tailwind utilities are not generated in this lane, so the
                fixture supplies it. The 44px rule under test is the CRM's. */}
            <a href="#/" style={{ display: "inline-flex" }}>
              1
            </a>
          </li>
        </ul>
      </nav>
      <div className="knowledge-source-detail">
        <section className="knowledge-detail-panel">{children}</section>
      </div>
    </div>
  </div>
);

const editPage = () => (
  <div className="knowledge-page-shell">
    <form className="knowledge-source-edit-form">
      <div className="knowledge-source-edit-fields">
        <label htmlFor="source-name">Tên tài liệu</label>
        <input id="source-name" />
        <label htmlFor="source-file">Tệp</label>
        <input id="source-file" />
      </div>
    </form>
  </div>
);

describe("knowledge source workspace layout", () => {
  it("keeps source navigation beside selected content on desktop", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(sourceWorkspace(<p>Nội dung</p>));
    const workspace = screen.container.querySelector<HTMLElement>(
      ".knowledge-source-workspace",
    )!;
    const navigation = screen.container.querySelector<HTMLElement>(
      ".knowledge-source-navigation",
    )!;
    const panel = screen.container.querySelector<HTMLElement>(
      ".knowledge-detail-panel",
    )!;

    const styles = getComputedStyle(workspace);
    expect(styles.display).toBe("grid");

    // The navigation track is clamped to 280-340px; the detail takes the rest,
    // so a long source name can never squeeze the content off the workspace.
    const navigationRect = navigation.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    expect(navigationRect.width).toBeGreaterThanOrEqual(280);
    expect(navigationRect.width).toBeLessThanOrEqual(340);
    expect(panelRect.left).toBeGreaterThanOrEqual(navigationRect.right - 1);
    expect(panelRect.width).toBeGreaterThan(navigationRect.width);

    // The dividing rule between the two tracks.
    const navStyles = getComputedStyle(navigation);
    expect(navStyles.borderRightWidth).toBe("1px");
    expect(navStyles.borderRightStyle).toBe("solid");
    // The detail panel sits inside the workspace, so it must not repeat the
    // page-level top rule.
    expect(getComputedStyle(panel).borderTopWidth).toBe("0px");
  });

  it("stacks the selected content below the source list on phones", async () => {
    await page.viewport(phone, 844);

    const screen = await render(sourceWorkspace(<p>Nội dung</p>));
    const workspace = screen.container.querySelector<HTMLElement>(
      ".knowledge-source-workspace",
    )!;
    const navigation = screen.container.querySelector<HTMLElement>(
      ".knowledge-source-navigation",
    )!;
    const panel = screen.container.querySelector<HTMLElement>(
      ".knowledge-detail-panel",
    )!;

    expect(getComputedStyle(workspace).display).toBe("block");

    // Stacked, and the list rules the content horizontally so the rule moves
    // from a vertical divider to a horizontal one.
    const navigationRect = navigation.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    expect(panelRect.top).toBeGreaterThanOrEqual(navigationRect.bottom - 1);
    const navStyles = getComputedStyle(navigation);
    expect(navStyles.borderRightWidth).toBe("0px");
    expect(navStyles.borderBottomWidth).toBe("1px");

    // Nothing may push the workspace wider than the phone viewport.
    expect(workspace.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
    expect(workspace.getBoundingClientRect().width).toBeCloseTo(
      window.innerWidth,
      0,
    );

    const panelStyles = getComputedStyle(panel);
    expect(panelStyles.minHeight).toBe("0px");
    expect(panelStyles.paddingTop).toBe("16px");
    expect(panelStyles.paddingLeft).toBe("0px");
  });

  it("keeps every source and pagination control at least 44px tall", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(sourceWorkspace(<p>Nội dung</p>));
    const button = screen.getByRole("button", { name: "Thêm nguồn" }).element();
    const pageLink = screen.container.querySelector<HTMLElement>(
      ".knowledge-source-pagination a",
    )!;

    expect(getComputedStyle(button).minHeight).toBe("44px");
    expect(button.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    expect(pageLink.getBoundingClientRect().width).toBeGreaterThanOrEqual(44);
    expect(pageLink.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
  });

  it("keeps knowledge disclosures compact and inside the phone viewport", async () => {
    await page.viewport(phone, 844);

    const screen = await render(
      <div className="knowledge-page-shell">
        <details className="knowledge-unit-disclosure">
          <summary>
            <span>Câu hỏi</span>
            <span className="knowledge-unit-chevron">▾</span>
          </summary>
          <div className="knowledge-unit-body">Nội dung</div>
        </details>
      </div>,
    );

    const disclosure = screen.container.querySelector<HTMLElement>(
      ".knowledge-unit-disclosure",
    )!;
    const summary = disclosure.querySelector<HTMLElement>("summary")!;
    const chevron = disclosure.querySelector<HTMLElement>(
      ".knowledge-unit-chevron",
    )!;

    expect(summary.getBoundingClientRect().height).toBeGreaterThanOrEqual(68);

    // Closed chevron points down; opening the disclosure flips it.
    expect(getComputedStyle(chevron).transform).not.toContain("matrix(-1");
    disclosure.setAttribute("open", "");
    await expect
      .poll(() => getComputedStyle(chevron).transform)
      .toContain("matrix(-1");

    expect(disclosure.getBoundingClientRect().right).toBeLessThanOrEqual(
      window.innerWidth,
    );
  });

  it("lays the source edit fields out as a label column on desktop", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(editPage());
    const form = screen.container.querySelector<HTMLElement>(
      ".knowledge-source-edit-form",
    )!;
    const fields = screen.container.querySelector<HTMLElement>(
      ".knowledge-source-edit-fields",
    )!;
    const label = fields.querySelector<HTMLElement>("label")!;
    const input = fields.querySelector<HTMLElement>("input")!;

    // The dedicated subpage stays flat: rules above and below, no card.
    const formStyles = getComputedStyle(form);
    expect(formStyles.borderTopWidth).toBe("1px");
    expect(formStyles.borderBottomWidth).toBe("1px");
    expect(formStyles.borderTopStyle).toBe("solid");

    expect(getComputedStyle(fields).display).toBe("grid");
    expect(label.getBoundingClientRect().width).toBeCloseTo(152, 0);
    expect(input.getBoundingClientRect().width).toBeGreaterThan(152);
  });

  it("stacks the source edit fields on phones", async () => {
    await page.viewport(phone, 844);

    const screen = await render(editPage());
    const fields = screen.container.querySelector<HTMLElement>(
      ".knowledge-source-edit-fields",
    )!;
    const children = Array.from(fields.children) as HTMLElement[];

    expect(getComputedStyle(fields).display).toBe("grid");
    expect(children).toHaveLength(4);
    // One column: every row shares the same left edge, and the second row sits
    // below the first.
    const [label, input] = children;
    expect(input.getBoundingClientRect().left).toBeCloseTo(
      label.getBoundingClientRect().left,
      0,
    );
    expect(children[2].getBoundingClientRect().top).toBeGreaterThan(
      input.getBoundingClientRect().bottom - 1,
    );
  });
});
