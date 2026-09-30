import { describe, expect, it } from "vitest";

import {
  buildStaticRecruitmentRuntime,
  getStaticRecruitmentRuntimeKey,
} from "./static-recruitment-runtime";

describe("static recruitment runtime", () => {
  it("builds the complete fixed recruitment workspace", () => {
    const runtime = buildStaticRecruitmentRuntime(7);

    expect(runtime.key).toBe("recruitment:7");
    expect(runtime.packKey).toBe("recruitment");
    expect(runtime.resources.map(({ name }) => name)).toEqual([
      "conversations",
      "bot_runs",
      "projects",
      "personas",
      "settings",
      "users",
    ]);
    expect(
      runtime.routes.map(({ id, path, layout }) => ({ id, path, layout })),
    ).toEqual([
      { id: "kernel.route.performance", path: "/hieu-suat", layout: "layout" },
      { id: "kernel.route.profile", path: "/profile", layout: "layout" },
      {
        id: "kernel.route.settings-profile-redirect",
        path: "/settings/profile",
        layout: "layout",
      },
      {
        id: "channel.zalo.route.legacy-settings-redirect",
        path: "/zalo_integrations/*",
        layout: "layout",
      },
      {
        id: "kernel.route.forgot-password",
        path: "/forgot-password",
        layout: "no-layout",
      },
    ]);
    expect(
      runtime.navigation.map(({ id, to, roles, section }) => ({
        id,
        to,
        roles,
        section,
      })),
    ).toEqual([
      { id: "overview", to: "/", roles: undefined, section: "operations" },
      {
        id: "messages",
        to: "/conversations",
        roles: undefined,
        section: "operations",
      },
      {
        id: "projects",
        to: "/projects",
        roles: undefined,
        section: "operations",
      },
      {
        id: "personas",
        to: "/personas",
        roles: ["admin"],
        section: "team",
      },
      { id: "users", to: "/users", roles: ["admin"], section: "team" },
      {
        id: "settings",
        to: "/settings",
        roles: ["admin"],
        section: "system",
      },
      {
        id: "bot_runs",
        to: "/bot_runs",
        roles: ["admin"],
        section: "system",
      },
      {
        id: "performance",
        to: "/hieu-suat",
        roles: ["admin"],
        section: "system",
      },
    ]);
    const navigationById = new Map(
      runtime.navigation.map((destination) => [destination.id, destination]),
    );
    expect(navigationById.get("overview")?.isActive("/")).toBe(true);
    expect(navigationById.get("overview")?.isActive("/projects")).toBe(false);
    expect(navigationById.get("messages")?.isActive("/conversations/1")).toBe(
      true,
    );
    expect(navigationById.get("projects")?.isActive("/projects/1")).toBe(true);
    expect(navigationById.get("personas")?.isActive("/personas")).toBe(true);
    expect(navigationById.get("users")?.isActive("/users/7")).toBe(true);
    expect(navigationById.get("users")?.isActive("/settings")).toBe(false);
    expect(navigationById.get("settings")?.isActive("/settings")).toBe(true);
    expect(navigationById.get("settings")?.isActive("/zalo_integrations")).toBe(
      true,
    );
    expect(navigationById.get("bot_runs")?.isActive("/bot_runs/1")).toBe(true);
    expect(
      navigationById.get("performance")?.isActive("/hieu-suat/weekly"),
    ).toBe(true);
    expect(runtime.dashboard).toBeTypeOf("function");
    expect(runtime.conversationSlots).toMatchObject({
      row: expect.any(Object),
      filters: expect.any(Object),
      context: expect.any(Function),
      actions: expect.any(Function),
    });
    expect(runtime.availableResources).toEqual(
      new Set(runtime.resources.map(({ name }) => name)),
    );
  });

  it("changes only when server authority generation changes", () => {
    expect(getStaticRecruitmentRuntimeKey(4)).toBe("recruitment:4");
    expect(getStaticRecruitmentRuntimeKey(5)).toBe("recruitment:5");
  });
});
