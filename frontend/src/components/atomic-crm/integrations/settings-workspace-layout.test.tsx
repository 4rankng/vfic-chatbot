import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";

import { SettingsGroup, SettingsSectionPanel } from "./SettingsGroup";
import { SettingsFieldStatus, SettingsGroupStatus } from "./SettingsFieldStatus";
import "@/index.css";
import "../conversations/inbox.css";
import "./settings.css";

// TEST-17 — this replaces settings.css.test.ts, which read settings.css,
// features.css and eleven `?raw` TSX sources and asserted ~24 regexes against
// them. Every assertion below is a measured value on the real SettingsGroup /
// SettingsSectionPanel / SettingsGroupStatus markup inside the real
// `.settings-workspace-content` shell, so a rule that is shadowed, scoped to an
// element the console never renders, or moved to the wrong breakpoint goes red.
//
// The `not.toContain("tt-card")` and `toContain("SettingsGroupStatus")` source
// pins become rendered checks: the group renders as a `.settings-group` frame
// with no `tt-card` element anywhere inside it, and it renders the real
// SettingsGroupStatus output.
//
// The design tokens `--settings-border` / `--settings-elevated` /
// `--border-strong` live on `.inbox-bg-container.settings-workspace` in
// features.css. They are set up here on the same wrapper the console uses, so
// the colour assertions below measure a real painted surface rather than a
// fallback.

const desktop = 1280;
const phone = 390;

afterEach(async () => {
  await cleanup();
  await page.viewport(desktop, 720);
});

const console = (children: React.ReactNode) => (
  <div
    className="inbox-bg-container settings-workspace"
    style={
      {
        "--settings-border": "#d4dce6",
        "--settings-elevated": "#ffffff",
        "--border-strong": "#0b1b2b",
      } as React.CSSProperties
    }
  >
    <div className="settings-workspace-content">
      <header className="settings-command-header">
        <h1>Cài đặt</h1>
      </header>
      <button type="button" className="settings-mobile-drawer-trigger">
        Mục cục
      </button>
      <SettingsSectionPanel id="providers">
        {/* `grid` is a Tailwind utility the console applies; the CRM stylesheet
            owns the track sizing, which is what this fixture measures. */}
        <div className="settings-grid-models" style={{ display: "grid" }}>
          <div className="settings-group-content">a</div>
          <div className="settings-group-content">b</div>
          <div className="settings-group-content">c</div>
        </div>
      </SettingsSectionPanel>
      {children}
    </div>
  </div>
);

const group = (children: React.ReactNode) => (
  <SettingsGroup
    id="test-group"
    title="Kênh Zalo"
    description="Kết nối kênh"
    icon={<span>Z</span>}
    meta={<SettingsGroupStatus configured={2} total={3} />}
    defaultOpen
  >
    {children}
  </SettingsGroup>
);

describe("settings workspace density scale", () => {
  it("scopes one density scale to the settings content, not the page", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(
      console(
        <div data-testid="outside">
          <span>ngoài</span>
        </div>,
      ),
    );

    const scoped = screen.container.querySelector<HTMLElement>(
      ".settings-workspace-content",
    )!;
    const styles = getComputedStyle(scoped);
    expect(styles.getPropertyValue("--settings-control-height").trim()).toBe("38px");
    expect(styles.getPropertyValue("--settings-action-height").trim()).toBe("36px");
    expect(styles.getPropertyValue("--settings-touch-target").trim()).toBe("44px");
    expect(styles.getPropertyValue("--settings-mobile-row-height").trim()).toBe(
      "48px",
    );

    // Scoping, not merely existing: the scale is declared on the settings
    // content surface, so the workspace shell that *contains* it — the node a
    // leak would reach from `:root` or a body-level rule — carries none of it.
    const shell = screen.container.querySelector<HTMLElement>(
      ".inbox-bg-container",
    )!;
    const shellScale = getComputedStyle(shell);
    for (const token of [
      "--settings-control-height",
      "--settings-action-height",
      "--settings-touch-target",
      "--settings-mobile-row-height",
    ]) {
      expect(shellScale.getPropertyValue(token).trim(), token).toBe("");
    }
  });
});

describe("settings configuration group card", () => {
  it("renders each group as an elevated card with a rounded frame", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(
      console(group(<button type="button" className="settings-test-button">Kiểm tra</button>)),
    );
    const card = screen.container.querySelector<HTMLElement>(".settings-group")!;
    const styles = getComputedStyle(card);

    // The card contract: 1px frame, 12px radius, elevated surface (not flat).
    expect(styles.borderTopWidth).toBe("1px");
    expect(styles.borderTopStyle).toBe("solid");
    expect(styles.borderRadius).toBe("12px");
    expect(styles.backgroundColor).toBe("rgb(255, 255, 255)");
    // The flat-surfaces contract: no shadow, no elevated-only radius from the kit.
    expect(styles.boxShadow).toBe("none");
    expect(card.querySelector(".tt-card")).toBeNull();
    expect(card.className).not.toContain("tt-card");
  });

  it("strengthens the frame on hover", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(console(group(<span />)));
    const card = screen.container.querySelector<HTMLElement>(".settings-group")!;
    const resting = getComputedStyle(card).borderTopColor;

    await page.elementLocator(card).hover();
    await expect
      .poll(() => getComputedStyle(card).borderTopColor)
      .not.toBe(resting);
    expect(getComputedStyle(card).borderTopWidth).toBe("1px");
  });

  it("tints the group header band separately from the card body", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(console(group(<span />)));
    const header = screen.container.querySelector<HTMLElement>(
      ".settings-group-header",
    )!;
    const content = screen.container.querySelector<HTMLElement>(
      ".settings-group-content",
    )!;

    const headerStyles = getComputedStyle(header);
    expect(headerStyles.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
    expect(headerStyles.backgroundColor).not.toBe(
      getComputedStyle(content).backgroundColor,
    );
    expect(headerStyles.borderBottomWidth).toBe("1px");
    expect(headerStyles.minHeight).toBe("36px");
  });

  it("renders the group status summary the provider cards depend on", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(console(group(<span />)));
    const meta = screen.container.querySelector<HTMLElement>(
      ".settings-group-meta",
    )!;

    expect(meta.textContent).toContain("2");
    expect(meta.textContent).toContain("3");
  });
});

describe("settings section panel", () => {
  it("spaces the panel with the scale token and adds no edge rule of its own", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(console(group(<span />)));
    const panel = screen.container.querySelector<HTMLElement>(
      ".settings-section-panel",
    )!;
    const styles = getComputedStyle(panel);

    expect(styles.gap).toBe("16px");
    expect(styles.borderTopWidth).toBe("0px");
    expect(styles.borderBottomWidth).toBe("0px");
  });

  it("compares provider cards side by side on wide screens", async () => {
    await page.viewport(1280, 900);

    const screen = await render(console(group(<span />)));
    const grid = screen.container.querySelector<HTMLElement>(
      ".settings-grid-models",
    )!;
    const tracks = Array.from(grid.children) as HTMLElement[];

    expect(getComputedStyle(grid).display).toBe("grid");
    expect(tracks).toHaveLength(3);
    const rects = tracks.map((track) => track.getBoundingClientRect());
    // Three equal tracks on one row: a two-column fallback kept the widths
    // equal but pushed the third provider onto its own line, where it read as a
    // different tier instead of a peer.
    expect(rects[1].width).toBeCloseTo(rects[0].width, 0);
    expect(rects[2].width).toBeCloseTo(rects[0].width, 0);
    expect(rects[1].top).toBeCloseTo(rects[0].top, 0);
    expect(rects[2].top).toBeCloseTo(rects[0].top, 0);
    expect(rects[2].left).toBeGreaterThan(rects[1].right - 1);
  });

  it("stacks the provider cards on a single-column desktop", async () => {
    await page.viewport(1000, 900);

    const screen = await render(console(group(<span />)));
    const tracks = Array.from(
      screen.container.querySelectorAll<HTMLElement>(
        ".settings-grid-models > .settings-group-content",
      ),
    );

    expect(tracks[1].getBoundingClientRect().top).toBeGreaterThanOrEqual(
      tracks[0].getBoundingClientRect().bottom - 1,
    );
  });
});

describe("settings action sizing", () => {
  it("uses compact desktop controls", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(
      console(group(<button type="button" className="settings-test-button">Kiểm tra</button>)),
    );
    const button = screen.getByRole("button", { name: "Kiểm tra" }).element();

    expect(getComputedStyle(button).minHeight).toBe("36px");
    expect(getComputedStyle(button).height).toBe("36px");
  });

  it("restores full mobile touch targets", async () => {
    await page.viewport(phone, 844);

    const screen = await render(
      console(group(<button type="button" className="settings-test-button">Kiểm tra</button>)),
    );
    const button = screen.getByRole("button", { name: "Kiểm tra" }).element();

    expect(getComputedStyle(button).minHeight).toBe("44px");
    expect(getComputedStyle(button).height).toBe("44px");
  });

  it("keeps the mobile navigation trigger and group rows touch-safe", async () => {
    await page.viewport(phone, 844);

    const screen = await render(console(group(<span />)));
    const trigger = screen.container.querySelector<HTMLElement>(
      ".settings-mobile-drawer-trigger",
    )!;
    const summary = screen.container.querySelector<HTMLElement>(
      ".settings-mobile-group-summary",
    )!;
    const header = screen.container.querySelector<HTMLElement>(
      ".settings-mobile-group .settings-group-header",
    )!;
    const pageTitle = screen.container.querySelector<HTMLElement>(
      ".settings-command-header h1",
    )!;

    expect(getComputedStyle(trigger).minHeight).toBe("44px");
    expect(summary.getBoundingClientRect().height).toBeGreaterThanOrEqual(48);
    // The collapse row must not re-inherit the details padding that ships with
    // `<details>`, which pushed the chevron off the row.
    expect(getComputedStyle(summary).paddingTop).toBe("0px");
    expect(getComputedStyle(summary).paddingLeft).toBe("0px");
    expect(getComputedStyle(header).minHeight).toBe("48px");
    // The page title stays on the shared page-title scale (22px at phone width).
    expect(getComputedStyle(pageTitle).fontSize).toBe("22px");
  });

  it("keeps mobile Messenger actions content-sized", async () => {
    await page.viewport(phone, 844);

    const screen = await render(
      console(
        <div className="settings-messenger">
          <form className="settings-messenger-recovery-form">
            <button type="button" className="settings-test-button">
              Thử lại
            </button>
          </form>
          <button type="button" className="settings-messenger-primary-action">
            Kết nối
          </button>
        </div>,
      ),
    );
    const form = screen.container.querySelector<HTMLElement>(
      ".settings-messenger-recovery-form",
    )!;
    const retry = form.querySelector<HTMLElement>(".settings-test-button")!;
    const primary = screen.container.querySelector<HTMLElement>(
      ".settings-messenger-primary-action",
    )!;

    // `width: max-content` keeps a short label short instead of stretching the
    // action across the recovery form.
    expect(getComputedStyle(retry).width).not.toBe("auto");
    expect(retry.getBoundingClientRect().width).toBeLessThan(
      form.getBoundingClientRect().width,
    );
    expect(primary.getBoundingClientRect().width).toBeLessThan(
      screen.container
        .querySelector<HTMLElement>(".settings-messenger")!
        .getBoundingClientRect().width,
    );
  });

  it("lays out the field status marker as a fixed 20px square", async () => {
    await page.viewport(desktop, 720);

    const screen = await render(console(<SettingsFieldStatus configured={false} />));
    const marker = screen.container.querySelector<HTMLElement>(
      ".settings-field-status",
    )!;
    const styles = getComputedStyle(marker);

    expect(styles.width).toBe("20px");
    expect(styles.height).toBe("20px");
    // A rounded chip here read as a pill badge in the middle of a form row.
    expect(styles.borderRadius).toBe("0px");
  });
});
