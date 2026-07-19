import { cleanup, render } from "vitest-browser-react";
import { page } from "vitest/browser";
import { afterEach, describe, expect, it } from "vitest";
import { BriefcaseBusiness, Home, MessageCircle, MoreHorizontal, Settings } from "lucide-react";

import "@/index.css";
import "./mobile-workspace.css";

afterEach(async () => {
  await cleanup();
  await page.viewport(1280, 720);
});

describe("mobile workspace dock", () => {
  it("keeps every icon and Vietnamese label inside its navigation item", async () => {
    await page.viewport(320, 844);
    await document.fonts.ready;
    const destinations = [
      ["Tổng quan", Home],
      ["Tin nhắn", MessageCircle],
      ["Dự án", BriefcaseBusiness],
      ["Cài đặt", Settings],
      ["Thêm", MoreHorizontal],
    ] as const;

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
      expect(Number.parseFloat(getComputedStyle(label).lineHeight)).toBeGreaterThan(
        Number.parseFloat(getComputedStyle(label).fontSize),
      );
    });
  });
});
