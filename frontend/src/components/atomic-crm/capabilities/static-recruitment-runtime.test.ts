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
      "knowledge_sources",
      "knowledge_bases",
      "projects",
      "personas",
      "settings",
      "users",
    ]);
    expect(runtime.routes.map(({ id, path, layout }) => ({ id, path, layout }))).toEqual([
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
      runtime.navigation.map(({ id, to, roles, rail, mobile }) => ({
        id,
        to,
        roles,
        rail,
        mobile,
      })),
    ).toEqual([
      { id: "overview", to: "/", roles: undefined, rail: true, mobile: true },
      {
        id: "messages",
        to: "/conversations",
        roles: undefined,
        rail: true,
        mobile: true,
      },
      { id: "projects", to: "/projects", roles: undefined, rail: true, mobile: true },
      {
        id: "settings",
        to: "/settings",
        roles: ["admin"],
        rail: true,
        mobile: true,
      },
      {
        id: "performance",
        to: "/hieu-suat",
        roles: ["admin"],
        rail: true,
        mobile: false,
      },
      { id: "account", to: "/profile", roles: undefined, rail: false, mobile: true },
    ]);
    const navigationById = new Map(runtime.navigation.map((destination) => [destination.id, destination]));
    expect(navigationById.get("overview")?.isActive("/")).toBe(true);
    expect(navigationById.get("overview")?.isActive("/projects")).toBe(false);
    expect(navigationById.get("messages")?.isActive("/conversations/1")).toBe(true);
    expect(navigationById.get("projects")?.isActive("/projects/1")).toBe(true);
    expect(navigationById.get("settings")?.isActive("/knowledge_sources")).toBe(true);
    expect(navigationById.get("performance")?.isActive("/hieu-suat/weekly")).toBe(true);
    expect(navigationById.get("account")?.isActive("/users/1")).toBe(true);
    expect(runtime.dashboard).toBeTypeOf("function");
    expect(runtime.conversationSlots).toMatchObject({
      row: expect.any(Object),
      filters: expect.any(Object),
      context: expect.any(Function),
      actions: expect.any(Function),
    });
    expect(runtime.availableResources).toEqual(new Set(runtime.resources.map(({ name }) => name)));
  });

  it("changes only when server authority generation changes", () => {
    expect(getStaticRecruitmentRuntimeKey(4)).toBe("recruitment:4");
    expect(getStaticRecruitmentRuntimeKey(5)).toBe("recruitment:5");
  });
});
