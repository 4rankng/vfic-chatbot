import { describe, expect, it } from "vitest";

import {
  getWorkspaceDestinations,
  normalizeWorkspacePath,
} from "./workspace-navigation";

describe("workspace navigation", () => {
  it("normalizes browser and React Admin hash paths", () => {
    expect(normalizeWorkspacePath("#/conversations?id=42")).toBe(
      "/conversations",
    );
    expect(normalizeWorkspacePath("projects/123?tab=team")).toBe(
      "/projects/123",
    );
  });

  it("keeps the approved desktop order for administrators", () => {
    expect(
      getWorkspaceDestinations("admin", "desktop").map(({ label }) => label),
    ).toEqual([
      "Tổng quan",
      "Tin nhắn",
      "Dự án",
      "Cài đặt",
      "Hiệu suất",
      "Tài khoản",
    ]);
  });

  it("keeps settings hidden from recruiters and account available on mobile", () => {
    expect(
      getWorkspaceDestinations("recruiter", "mobile").map(({ label }) => label),
    ).toEqual(["Tổng quan", "Tin nhắn", "Dự án", "Tài khoản"]);
  });

  it("keeps the approved four-item mobile set for administrators", () => {
    expect(
      getWorkspaceDestinations("admin", "mobile").map(({ label }) => label),
    ).toEqual(["Tổng quan", "Tin nhắn", "Dự án", "Cài đặt"]);
  });

  it("matches nested workspace routes", () => {
    const settings = getWorkspaceDestinations("admin", "desktop").find(
      ({ id }) => id === "settings",
    );
    expect(settings?.isActive("/knowledge_sources/documents")).toBe(true);
  });
});
