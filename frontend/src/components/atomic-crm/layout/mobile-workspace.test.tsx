import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";
import {
  BriefcaseBusiness,
  Home,
  MessageCircle,
  MoreHorizontal,
  Settings,
} from "lucide-react";

import "@/index.css";
import workspaceStyles from "@/index.css?raw";
import "./desktop-workspace.css";
import "./mobile-workspace.css";

const destinations = [
  ["Tổng quan", Home],
  ["Tin nhắn", MessageCircle],
  ["Dự án", BriefcaseBusiness],
  ["Cài đặt", Settings],
  ["Thêm", MoreHorizontal],
] as const;

const activeNavigationRules = Array.from(
  workspaceStyles.matchAll(
    /\.(?:workspace-navigation-link|workspace-navigation-(?:rail|mobile)\s+\.workspace-navigation-link)\.is-active\s*\{[^}]*\}/g,
  ),
  ([rule]) => rule,
).join("\n");

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 720);
});

describe("desktop workspace rail", () => {
  it("keeps the compact TingHire mark in an icon-only rail at desktop and tablet widths", async () => {
    await page.viewport(1280, 720);

    const screen = await render(
      <div className="workspace-frame">
        <header className="workspace-topbar">
          <a className="workspace-topbar-brand" href="#/">
            <img
              src="/brand/tinghire-icon-transparent.png"
              alt=""
              aria-hidden="true"
            />
            <span>TingHire</span>
          </a>
        </header>
        <nav className="workspace-navigation-rail">
          <a
            className="workspace-sidebar-brand"
            href="#/"
            aria-label="TingHire - về trang tổng quan"
          >
            <img
              className="workspace-sidebar-brand-mark"
              src="/brand/tinghire-icon-rail.png"
              alt=""
            />
          </a>
          <div className="workspace-navigation-items" />
        </nav>
        <main className="workspace-frame-content" />
      </div>,
    );

    const rail = screen.container.querySelector<HTMLElement>(
      ".workspace-navigation-rail",
    )!;
    const compactMark = screen.container.querySelector<HTMLElement>(
      ".workspace-sidebar-brand-mark",
    )!;
    const topbarBrand = screen.container.querySelector<HTMLElement>(
      ".workspace-topbar-brand",
    )!;
    const topbarBrandMark = topbarBrand.querySelector<HTMLElement>("img")!;
    const frame =
      screen.container.querySelector<HTMLElement>(".workspace-frame")!;
    const topbar =
      screen.container.querySelector<HTMLElement>(".workspace-topbar")!;

    expect(getComputedStyle(rail).width).toBe("72px");
    expect(getComputedStyle(frame).gridTemplateRows.split(" ")[0]).toBe("44px");
    expect(topbar.getBoundingClientRect().height).toBeCloseTo(44, 0);
    expect(getComputedStyle(compactMark).display).toBe("block");
    expect(getComputedStyle(compactMark).width).toBe("44px");
    expect(getComputedStyle(topbarBrand).display).toBe("none");

    await page.viewport(900, 720);

    expect(getComputedStyle(rail).width).toBe("72px");
    expect(topbar.getBoundingClientRect().height).toBeCloseTo(44, 0);
    expect(getComputedStyle(compactMark).display).toBe("block");
    expect(getComputedStyle(topbarBrand).display).not.toBe("none");
    expect(getComputedStyle(topbarBrandMark).borderTopWidth).toBe("0px");
    expect(getComputedStyle(topbarBrandMark).borderRadius).toBe("0px");
    expect(getComputedStyle(topbarBrandMark).objectFit).toBe("contain");
  });

  it("pins the notification and account controls to the far right of the top bar", async () => {
    await page.viewport(1280, 720);

    const screen = await render(
      <div className="workspace-frame">
        <header className="workspace-topbar">
          <a className="workspace-topbar-brand" href="#/">
            <span>TingHire</span>
          </a>
          <div className="workspace-topbar-actions">
            <button type="button">Thông báo</button>
            <button type="button">Tài khoản</button>
          </div>
        </header>
        <nav className="workspace-navigation-rail" />
        <main className="workspace-frame-content" />
      </div>,
    );

    const header =
      screen.container.querySelector<HTMLElement>(".workspace-topbar")!;
    const actions = screen.container.querySelector<HTMLElement>(
      ".workspace-topbar-actions",
    )!;
    const headerRect = header.getBoundingClientRect();
    const actionsRect = actions.getBoundingClientRect();

    expect(actionsRect.right).toBeCloseTo(headerRect.right - 12, 0);
  });

  it("wins the active-state cascade with the brand surface", async () => {
    const screen = await render(
      <div className="workspace-frame">
        <style>{`
          .workspace-frame {
            --color-uu-brand-500: #f15a3a;
            --workspace-action: #b73522;
            --workspace-shell-active: #24304a;
            --workspace-shell-rail-active: #fff6ed;
          }
          ${activeNavigationRules}
        `}</style>
        <nav className="workspace-navigation-rail">
          <a className="workspace-navigation-link is-active">
            <MessageCircle />
          </a>
        </nav>
        <nav className="workspace-navigation-mobile">
          <a className="workspace-navigation-link is-active">
            <MessageCircle />
          </a>
        </nav>
      </div>,
    );

    const desktopActive = screen.container.querySelector<HTMLElement>(
      ".workspace-navigation-rail .workspace-navigation-link.is-active",
    )!;
    const mobileActive = screen.container.querySelector<HTMLElement>(
      ".workspace-navigation-mobile .workspace-navigation-link.is-active",
    )!;

    expect(getComputedStyle(desktopActive).backgroundColor).toBe(
      "rgb(255, 246, 237)",
    );
    expect(getComputedStyle(mobileActive).backgroundColor).not.toBe(
      "rgb(255, 246, 237)",
    );
  });
});

describe("mobile workspace dock", () => {
  it("spans the viewport at intermediate mobile widths", async () => {
    await page.viewport(491, 880);

    const screen = await render(
      <nav className="workspace-navigation workspace-navigation-mobile tt-menu">
        <div className="workspace-navigation-items workspace-navigation-items--with-overflow">
          {destinations.map(([label, Icon]) => (
            <a
              key={label}
              href={`#/${label}`}
              className="workspace-navigation-link tt-btn tt-btn-ghost"
            >
              <span className="workspace-navigation-icon" aria-hidden="true">
                <Icon />
              </span>
              <span className="workspace-navigation-label">{label}</span>
            </a>
          ))}
        </div>
      </nav>,
    );

    const navigation = screen.container.querySelector<HTMLElement>(
      ".workspace-navigation-mobile",
    )!;
    const items = navigation.querySelector<HTMLElement>(
      ".workspace-navigation-items",
    )!;
    const navigationRect = navigation.getBoundingClientRect();
    const itemsRect = items.getBoundingClientRect();

    expect(navigationRect.left).toBeCloseTo(0, 0);
    expect(navigationRect.right).toBeCloseTo(window.innerWidth, 0);
    expect(itemsRect.left).toBeCloseTo(12, 0);
    expect(itemsRect.right).toBeCloseTo(window.innerWidth - 12, 0);
  });

  it("keeps every icon and Vietnamese label inside its navigation item", async () => {
    await page.viewport(320, 844);
    await document.fonts.ready;

    const screen = await render(
      <nav className="workspace-navigation workspace-navigation-mobile tt-menu">
        <div className="workspace-navigation-items workspace-navigation-items--with-overflow">
          {destinations.map(([label, Icon], index) => (
            <button
              key={label}
              type="button"
              className={`workspace-navigation-link tt-btn tt-btn-ghost${index === 2 ? " is-active" : ""}`}
            >
              <span className="workspace-navigation-icon" aria-hidden="true">
                <Icon />
              </span>
              <span className="workspace-navigation-label">{label}</span>
            </button>
          ))}
        </div>
      </nav>,
    );

    const links = screen.container.querySelectorAll<HTMLElement>(
      ".workspace-navigation-link",
    );
    expect(links).toHaveLength(5);

    links.forEach((link) => {
      const linkRect = link.getBoundingClientRect();
      const iconRect = link
        .querySelector<HTMLElement>(".workspace-navigation-icon")!
        .getBoundingClientRect();
      const label = link.querySelector<HTMLElement>(
        ".workspace-navigation-label",
      )!;
      const labelRect = label.getBoundingClientRect();

      expect(labelRect.left).toBeGreaterThanOrEqual(linkRect.left - 0.5);
      expect(labelRect.right).toBeLessThanOrEqual(linkRect.right + 0.5);
      expect(label.scrollWidth).toBeLessThanOrEqual(label.clientWidth + 1);
      expect(iconRect.top).toBeGreaterThanOrEqual(linkRect.top);
      expect(labelRect.bottom).toBeLessThanOrEqual(linkRect.bottom);
      expect(
        Number.parseFloat(getComputedStyle(label).lineHeight),
      ).toBeGreaterThan(Number.parseFloat(getComputedStyle(label).fontSize));
    });
  });
});
