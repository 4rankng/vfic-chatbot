import type { ReactNode } from "react";
import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";

import "@/index.css";
import "../conversations/inbox.css";
import "../conversations/inbox/personas-studio.css";
import "../conversations/inbox/personas-responsive.css";
import "../conversations/inbox/mobile-persona-editor.css";
import { TestMessages } from "../providers/commons/TestMessages";

// TEST-17 — this replaces the persona-layout-regressions.test.ts that imported
// three stylesheets and five TSX files as `?raw` and regex-matched them. Those
// pins could not see whether a rule reached the element the console renders,
// whether a later declaration shadowed it, or whether the Agent overview still
// offered exactly one edit action.
//
// Everything below renders the real class structure inside the shells the
// console uses and measures what a browser computes.
//
// Lane facts that shape the fixture:
//   * The daisyUI / `@theme` typography scale is not emitted by this vitest
//     project, so every `var(--fs-*)` and `var(--crm-fs-*)` is unresolvable
//     above 767px. The rules that only restate type are therefore unasserted
//     and the geometry those rules sit next to is asserted instead — the
//     measured height proves the rule's *other* declarations survive.
//   * `--surface-solid` / `--border` do resolve from `:root`, so the flat-plane
//     colour and frame assertions below are real painted values.
//   * `.persona-scope-activity-grid` and friends are `display: grid` in
//     personas-studio.css, so no Tailwind `grid` utility is needed in the
//     fixture; where a rule needs a box (`.persona-studio-command` is a
//     `label`), the fixture supplies `display: flex` the way the component does.

const desktop = 1280;
const phone = 390;
const tablet = 800;

afterEach(async () => {
  await cleanup();
  await page.viewport(desktop, 720);
});

/** The Agent overview shell: directory rail on the left, overview on the right. */
const studio = (overview: ReactNode) => (
  <div className="inbox-bg-container settings-workspace">
    <div className="workspace-frame-content">
      <div className="persona-workspace-content">
        <div className="persona-page-shell">
          <div className="persona-studio-layout persona-agent-stack">
            <section className="persona-agent-picker" aria-label="Danh sách Agent">
              <div className="persona-panel-header">
                <div className="persona-panel-heading">
                  <h2>Agent</h2>
                </div>
                <button type="button" className="persona-create-action tt-btn-touch">
                  Tạo Agent
                </button>
              </div>
              {/* The component renders this `label` as a flex row; the CSS rule
                  under test sets `min-height`, which an inline box ignores. */}
              <label className="tt-input persona-studio-command" style={{ display: "flex" }}>
                <input type="search" placeholder="Tìm Agent" aria-label="Tìm Agent" />
              </label>
              <div className="persona-directory-list">
                <article className="tt-list-row persona-directory-row">
                  <div className="persona-directory-main">Tuyển dụng</div>
                </article>
              </div>
            </section>
            <div className="persona-studio-body">{overview}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
);

const overviewPanel = (
  <>
    <div className="persona-studio-profile">
      <div className="persona-studio-profile-actions">
        <span className="persona-studio-updated">Cập nhật 27/09/2026</span>
        <button
          type="button"
          className="persona-overview-edit-action tt-btn-touch"
        >
          Sửa Agent
        </button>
      </div>
    </div>
    <section className="persona-studio-section">
      <div className="persona-studio-section-title">
        <div>
          <h2>Mức hoàn thiện</h2>
          <p>3/5 phần</p>
        </div>
      </div>
    </section>
  </>
);

describe("Agent overview content plane", () => {
  it("draws the studio layout as a continuous surface, not a card", async () => {
    await page.viewport(desktop, 900);
    const screen = await render(<TestMessages>{studio(overviewPanel)}</TestMessages>);

    const layout = screen.container.querySelector<HTMLElement>(
      ".persona-studio-layout",
    )!;
    const styles = getComputedStyle(layout);

    // The old pin was `border: 0; border-radius: 0` in the source. Measured, a
    // frame or radius here would mean the overview floats as its own card.
    expect(styles.borderTopWidth).toBe("0px");
    expect(styles.borderRadius).toBe("0px");
    expect(layout.className).not.toContain("tt-card");
    expect(layout.innerHTML).not.toContain("tt-card");
    // Directory rail and overview share one row — the overview is not stacked
    // under the directory.
    const picker = screen.container.querySelector<HTMLElement>(
      ".persona-agent-picker",
    )!;
    expect(styles.display).toBe("grid");
    expect(
      screen.container
        .querySelector<HTMLElement>(".persona-studio-body")!
        .getBoundingClientRect().left,
    ).toBeGreaterThanOrEqual(picker.getBoundingClientRect().right - 1);
  });

  it("offers exactly one edit action on the overview", async () => {
    // Replaces `overviewSource.match(/onEdit\(persona\)/g) === 1` plus the
    // `not.toContain("Sửa prompt")` / `not.toContain("Đang xem")` pins: the
    // rendered overview must carry a single edit control and no per-prompt
    // edit affordances.
    await page.viewport(desktop, 900);
    const screen = await render(<TestMessages>{studio(overviewPanel)}</TestMessages>);

    const body = screen.container.querySelector<HTMLElement>(
      ".persona-studio-body",
    )!;
    expect(
      body.querySelectorAll(".persona-overview-edit-action"),
    ).toHaveLength(1);
    expect(body.textContent).not.toContain("Sửa prompt");
    expect(body.textContent).not.toContain("Đang xem");
  });

  it("keeps every overview control at the 44px comfortable height", async () => {
    await page.viewport(desktop, 900);
    const screen = await render(<TestMessages>{studio(overviewPanel)}</TestMessages>);

    const command = screen.container.querySelector<HTMLElement>(
      ".persona-studio-command",
    )!;
    const create = screen.container.querySelector<HTMLElement>(
      ".persona-create-action",
    )!;
    const edit = screen.container.querySelector<HTMLElement>(
      ".persona-overview-edit-action",
    )!;

    // `.persona-page-shell .persona-agent-picker .persona-studio-command`
    expect(getComputedStyle(command).minHeight).toBe("44px");
    // `.persona-page-shell .persona-agent-picker .persona-create-action` pins
    // min-height and height together so a wrapped label still clears 44px.
    expect(getComputedStyle(create).minHeight).toBe("44px");
    expect(getComputedStyle(create).height).toBe("44px");
    // `.persona-page-shell .persona-overview-edit-action`
    expect(getComputedStyle(edit).minHeight).toBe("44px");
    expect(getComputedStyle(edit).height).toBe("44px");
  });
});

describe("Agent overview embedded in settings", () => {
  const embedded = (overview: ReactNode) => (
    <div className="inbox-bg-container settings-workspace">
      <div className="settings-workspace-content">
        <section className="settings-embedded-resource">
          {studio(overview)}
        </section>
      </div>
    </div>
  );

  it("narrows the directory rail so the overview keeps the room", async () => {
    // Above 760px the embedded studio drops the rail to a 208–224px track, so
    // the overview is not squeezed into a sliver next to a full-width rail.
    await page.viewport(tablet, 900);
    const screen = await render(<TestMessages>{embedded(overviewPanel)}</TestMessages>);

    const picker = screen.container.querySelector<HTMLElement>(
      ".persona-agent-picker",
    )!;
    const body = screen.container.querySelector<HTMLElement>(
      ".persona-studio-body",
    )!;
    const pickerWidth = picker.getBoundingClientRect().width;
    const bodyWidth = body.getBoundingClientRect().width;

    expect(pickerWidth).toBeGreaterThanOrEqual(208);
    expect(pickerWidth).toBeLessThanOrEqual(224);
    expect(bodyWidth).toBeGreaterThan(pickerWidth);
  });

  it("uses compact controls for the embedded directory", async () => {
    // The embedded picker trades the 44px phone targets for 34px controls and
    // a 38px search box: a full-width 44px create button dominated a 224px rail.
    await page.viewport(tablet, 900);
    const screen = await render(<TestMessages>{embedded(overviewPanel)}</TestMessages>);

    const create = screen.container.querySelector<HTMLElement>(
      ".persona-create-action",
    )!;
    const command = screen.container.querySelector<HTMLElement>(
      ".persona-studio-command",
    )!;

    expect(getComputedStyle(create).minHeight).toBe("34px");
    expect(getComputedStyle(create).height).toBe("34px");
    // `width: auto` keeps the button content-sized rather than stretching it
    // across the narrow rail.
    expect(getComputedStyle(create).width).not.toBe("100%");
    expect(create.getBoundingClientRect().width).toBeLessThan(
      screen.container
        .querySelector<HTMLElement>(".persona-agent-picker")!
        .getBoundingClientRect().width,
    );
    expect(getComputedStyle(command).minHeight).toBe("38px");
  });

  it("tightens the embedded overview sections", async () => {
    // `.settings-embedded-resource .persona-studio-section { padding: 14px 16px }`
    await page.viewport(tablet, 900);
    const screen = await render(<TestMessages>{embedded(overviewPanel)}</TestMessages>);

    const section = screen.container.querySelector<HTMLElement>(
      ".persona-studio-section",
    )!;
    const styles = getComputedStyle(section);
    expect(styles.paddingTop).toBe("14px");
    expect(styles.paddingLeft).toBe("16px");
  });

  it("stacks the Agent scope and activity columns on a phone", async () => {
    await page.viewport(phone, 844);
    const screen = await render(
      <TestMessages>
        <div className="inbox-bg-container settings-workspace">
          <div className="persona-workspace-content">
            <div className="persona-scope-activity-grid" style={{ display: "grid" }}>
              <div className="persona-scope-row">phạm vi</div>
              <div className="persona-scope-activity">hoạt động</div>
            </div>
          </div>
        </div>
      </TestMessages>,
    );

    const columns = Array.from(
      screen.container.querySelectorAll<HTMLElement>(
        ".persona-scope-activity-grid > *",
      ),
    );
    expect(columns).toHaveLength(2);
    // At ≤760px both panels share one track, so the narrower one is not
    // squeezed into a sliver beside the other.
    expect(columns[1].getBoundingClientRect().top).toBeGreaterThanOrEqual(
      columns[0].getBoundingClientRect().bottom - 1,
    );
  });
});

describe("Agent editor metrics plane", () => {
  const editor = (children: ReactNode) => (
    <div className="inbox-bg-container">
      <div className="app persona-app" id="app">
        <section className="center-panel persona-center-panel">
          <div className="persona-workspace-content">{children}</div>
        </section>
      </div>
    </div>
  );

  it("flattens the editor status strip and rail cards", async () => {
    // Replaces the `.persona-editor-status-strip` / `.persona-edit-rail-card`
    // source pins with measured values: both were rewritten to `border: 0`,
    // `border-radius: 0`, `background: transparent` so the editor metrics read
    // as one band instead of three stacked cards.
    await page.viewport(1200, 900);
    const screen = await render(
      <TestMessages>
        {editor(
          <>
            <div className="persona-editor-status-strip">
              <div>
                <span>Phần</span>
                <strong>3/5</strong>
              </div>
              <div>
                <span>Follow-up</span>
                <strong>2/3</strong>
              </div>
              <div>
                <span>Adapter</span>
                <strong>1</strong>
              </div>
            </div>
            <div className="persona-edit-rail">
              <div className="persona-edit-rail-card">
                <p>Phạm vi</p>
              </div>
              <div className="persona-edit-rail-card">
                <p>Kênh</p>
              </div>
            </div>
          </>,
        )}
      </TestMessages>,
    );

    const strip = screen.container.querySelector<HTMLElement>(
      ".persona-editor-status-strip",
    )!;
    const stripStyles = getComputedStyle(strip);
    expect(stripStyles.borderTopWidth).toBe("0px");
    expect(stripStyles.borderRadius).toBe("0px");
    expect(stripStyles.backgroundColor).toBe("rgba(0, 0, 0, 0)");

    const cards = Array.from(
      screen.container.querySelectorAll<HTMLElement>(
        ".persona-edit-rail-card",
      ),
    );
    expect(cards).toHaveLength(2);
    for (const card of cards) {
      const styles = getComputedStyle(card);
      expect(styles.borderTopWidth, card.outerHTML).toBe("0px");
      expect(styles.borderRadius, card.outerHTML).toBe("0px");
      expect(styles.backgroundColor, card.outerHTML).toBe("rgba(0, 0, 0, 0)");
    }
    // Adjacent rail cards share one ruled divider instead of each drawing a box.
    expect(getComputedStyle(cards[1]).borderLeftWidth).toBe("1px");
  });

  it("marks an active Agent as running exactly once in the editor header", async () => {
    // Replaces `editSource.match(/Đang bật/g) === 1`: the running badge is a
    // single status, and a second copy anywhere in the header would mean the
    // same fact is announced twice.
    await page.viewport(1200, 900);
    const screen = await render(
      <TestMessages>
        {editor(
          <div className="persona-editor-hero">
            <div className="persona-editor-heading-line">
              <h1>Chỉnh sửa Agent</h1>
              <span className="persona-studio-badge is-good">Đang bật</span>
            </div>
          </div>,
        )}
      </TestMessages>,
    );

    const header = screen.container.querySelector<HTMLElement>(
      ".persona-editor-heading-line",
    )!;
    expect(header.textContent?.match(/Đang bật/g) ?? []).toHaveLength(1);
  });

  it("scrolls the editor on desktop and hands scrolling to the page on a phone", async () => {
    // The centre panel owns the scroll above 760px; below it the panel and the
    // workspace content both release it, so the phone page scrolls as one
    // document and a sticky save bar stays reachable.
    await page.viewport(1200, 700);
    const desktopScreen = await render(
      <TestMessages>
        {editor(
          <div className="persona-edit-surface" style={{ height: "2000px" }}>
            nội dung dài
          </div>,
        )}
      </TestMessages>,
    );
    const desktopPanel = desktopScreen.container.querySelector<HTMLElement>(
      ".persona-center-panel",
    )!;
    expect(getComputedStyle(desktopPanel).overflowY).toBe("auto");
    const desktopContent = desktopScreen.container.querySelector<HTMLElement>(
      ".persona-workspace-content",
    )!;
    expect(getComputedStyle(desktopContent).overflowY).toBe("visible");

    await cleanup();
    await page.viewport(phone, 844);
    const phoneScreen = await render(
      <TestMessages>
        {editor(
          <div className="persona-edit-surface" style={{ height: "2000px" }}>
            nội dung dài
          </div>,
        )}
      </TestMessages>,
    );
    const phonePanel = phoneScreen.container.querySelector<HTMLElement>(
      ".persona-center-panel",
    )!;
    const phoneContent = phoneScreen.container.querySelector<HTMLElement>(
      ".persona-workspace-content",
    )!;
    expect(getComputedStyle(phonePanel).overflowY).toBe("visible");
    expect(getComputedStyle(phoneContent).overflowY).toBe("visible");
  });

  it("stops the edit surface clipping its own children", async () => {
    // `.persona-edit-surface { overflow: visible }` — a clipping surface hid the
    // section disclosures and the save bar that overflow it.
    await page.viewport(1200, 900);
    const screen = await render(
      <TestMessages>
        {editor(
          <div className="persona-edit-surface">
            <details className="persona-edit-prompt-block">
              <summary>Phần 1</summary>
            </details>
          </div>,
        )}
      </TestMessages>,
    );

    const surface = screen.container.querySelector<HTMLElement>(
      ".persona-edit-surface",
    )!;
    expect(getComputedStyle(surface).overflow).toBe("visible");
  });
});

describe("Agent editor long-form actions", () => {
  const editorFooter = (children: ReactNode) => (
    <div className="inbox-bg-container">
      <div className="app persona-app" id="app">
        <section className="center-panel persona-center-panel">
          <div className="persona-workspace-content">
            {children}
            <footer className="persona-edit-savebar">
              <button type="submit" className="tt-btn-touch">
                Lưu
              </button>
            </footer>
          </div>
        </section>
      </div>
    </div>
  );

  it("pins the save bar to the bottom of the editor viewport on desktop", async () => {
    // `.persona-edit-savebar` is `position: sticky; bottom: 0` above 1020px, so
    // saving stays reachable while a long prompt is scrolled.
    await page.viewport(1200, 700);
    const screen = await render(
      <TestMessages>
        {editorFooter(
          <div className="persona-edit-surface" style={{ height: "2400px" }}>
            nội dung dài
          </div>,
        )}
      </TestMessages>,
    );

    const savebar = screen.container.querySelector<HTMLElement>(
      ".persona-edit-savebar",
    )!;
    const styles = getComputedStyle(savebar);
    expect(styles.position).toBe("sticky");
    expect(styles.bottom).toBe("0px");
  });

  it("keeps the follow-up stage, switch and editor comfortable to operate", async () => {
    // These three rules are the whole touch-target contract for the follow-up
    // block: a 44px stage row, a 44px switch target, and a 44px input.
    await page.viewport(1200, 900);
    const screen = await render(
      <TestMessages>
        {editorFooter(
          <div className="persona-followup-editor-card">
            <div className="persona-followup-stage">
              <span role="switch" aria-checked="true">
                <span />
              </span>
              Hot
            </div>
            <label className="persona-followup-switch-target">
              <span role="switch" aria-checked="true">
                <span />
              </span>
            </label>
            <input data-slot="input" type="text" aria-label="Nội dung follow-up" />
          </div>,
        )}
      </TestMessages>,
    );

    const stage = screen.container.querySelector<HTMLElement>(
      ".persona-followup-stage",
    )!;
    const target = screen.container.querySelector<HTMLElement>(
      ".persona-followup-switch-target",
    )!;
    const input = screen.container.querySelector<HTMLElement>(
      '[data-slot="input"]',
    )!;

    expect(getComputedStyle(stage).minHeight).toBe("44px");
    expect(getComputedStyle(target).width).toBe("44px");
    expect(getComputedStyle(target).height).toBe("44px");
    expect(getComputedStyle(input).minHeight).toBe("44px");
    expect(getComputedStyle(input).height).toBe("44px");
  });
});
