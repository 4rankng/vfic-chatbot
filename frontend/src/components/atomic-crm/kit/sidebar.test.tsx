import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { render } from "vitest-browser-react";
import { describe, expect, it } from "vitest";
import { Briefcase, Home, MessageCircle, Settings } from "lucide-react";

import { KitSidebar, type KitSidebarDestination } from "./sidebar";

const startsWith = (prefix: string) => (path: string) =>
  path === prefix || path.startsWith(`${prefix}/`);

const destinations: KitSidebarDestination[] = [
  {
    id: "overview",
    label: "Tổng quan",
    to: "/",
    Icon: Home,
    isActive: (p) => p === "/",
  },
  {
    id: "messages",
    label: "Tin nhắn",
    to: "/conversations",
    Icon: MessageCircle,
    isActive: startsWith("/conversations"),
  },
  {
    id: "projects",
    label: "Dự án",
    to: "/projects",
    Icon: Briefcase,
    isActive: startsWith("/projects"),
  },
];

const footerDestinations: KitSidebarDestination[] = [
  {
    id: "settings",
    label: "Cài đặt",
    to: "/settings",
    Icon: Settings,
    isActive: startsWith("/settings"),
  },
];

function wrap(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("KitSidebar", () => {
  it("renders the brand label and all destination labels in the expanded panel", async () => {
    const screen = await wrap(
      <KitSidebar
        brand={<span data-testid="brand">TT</span>}
        brandLabel="Ting Ting"
        sections={[{ id: "main", destinations }]}
        path="/"
      />,
    );
    expect(screen.getByText("Ting Ting")).toBeTruthy();
    expect(screen.getByText("Tổng quan")).toBeTruthy();
    expect(screen.getByText("Tin nhắn")).toBeTruthy();
    expect(screen.getByText("Dự án")).toBeTruthy();
  });

  it("marks the active destination with aria-current=page", async () => {
    const screen = await wrap(
      <KitSidebar
        brand={<span>TT</span>}
        sections={[{ id: "main", destinations }]}
        path="/conversations/42"
      />,
    );
    // The destination renders in BOTH the mini-rail and the expanded panel;
    // both copies must reflect active state. Query within the expanded panel
    // (which carries the visible label) to disambiguate from the rail shortcut.
    const panel = screen.container.querySelector(".tt-sidebar-panel");
    const panelLinks = panel?.querySelectorAll("a");
    const messagesLink = Array.from(panelLinks ?? []).find((a) =>
      a.textContent?.includes("Tin nhắn"),
    );
    const projectsLink = Array.from(panelLinks ?? []).find((a) =>
      a.textContent?.includes("Dự án"),
    );
    expect(messagesLink?.getAttribute("aria-current")).toBe("page");
    expect(projectsLink?.getAttribute("aria-current")).toBeNull();
  });

  it("renders a footer section in a separate region", async () => {
    const screen = await wrap(
      <KitSidebar
        brand={<span>TT</span>}
        sections={[{ id: "main", destinations }]}
        footerSections={[{ id: "account", destinations: footerDestinations }]}
        path="/"
      />,
    );
    expect(screen.getByText("Cài đặt")).toBeTruthy();
  });

  it("renders a badge when a destination has badge > 0", async () => {
    const messages = destinations.find((d) => d.id === "messages")!;
    const withBadge: KitSidebarDestination[] = [{ ...messages, badge: 7 }];
    const screen = await wrap(
      <KitSidebar
        brand={<span>TT</span>}
        sections={[{ id: "main", destinations: withBadge }]}
        path="/"
      />,
    );
    expect(screen.getByText("7")).toBeTruthy();
  });

  it("caps large badge counts at 99+", async () => {
    const messages = destinations.find((d) => d.id === "messages")!;
    const withBadge: KitSidebarDestination[] = [{ ...messages, badge: 250 }];
    const screen = await wrap(
      <KitSidebar
        brand={<span>TT</span>}
        sections={[{ id: "main", destinations: withBadge }]}
        path="/"
      />,
    );
    expect(screen.getByText("99+")).toBeTruthy();
  });

  it("hides a destination from the mini rail when showInRail is false", async () => {
    const projects = destinations.find((d) => d.id === "projects")!;
    const hiddenRail: KitSidebarDestination[] = [
      { ...projects, showInRail: false },
    ];
    const screen = await wrap(
      <KitSidebar
        brand={<span>TT</span>}
        sections={[{ id: "main", destinations: hiddenRail }]}
        path="/"
      />,
    );
    // The destination still appears in the expanded panel…
    expect(screen.getByText("Dự án")).toBeTruthy();
    // …but the mini rail excludes it entirely.
    const rail = screen.container.querySelector(".tt-sidebar-rail");
    const railLinks = rail?.querySelectorAll("a");
    expect(railLinks?.length).toBe(0);
  });

  it("renders section labels when provided", async () => {
    const screen = await wrap(
      <KitSidebar
        brand={<span>TT</span>}
        sections={[
          {
            id: "main",
            label: "Không gian",
            destinations,
          },
        ]}
        path="/"
      />,
    );
    expect(screen.getByText("Không gian")).toBeTruthy();
  });
});
