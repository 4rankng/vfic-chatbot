import { describe, expect, it } from "vitest";

import {
  getWorkspaceDestinations,
  getWorkspaceOverflowDestinations,
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

  it("keeps account access in the desktop icon rail", () => {
    expect(
      getWorkspaceDestinations("admin", "rail").map(({ label }) => label),
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

  it("keeps desktop-only admin destinations reachable through mobile overflow", () => {
    expect(
      getWorkspaceOverflowDestinations("admin").map(({ label }) => label),
    ).toEqual(["Hiệu suất", "Tài khoản"]);
    expect(getWorkspaceOverflowDestinations("recruiter")).toEqual([]);
  });

  it("matches nested workspace routes", () => {
    const settings = getWorkspaceDestinations("admin", "rail").find(
      ({ id }) => id === "settings",
    );
    expect(settings?.isActive("/knowledge_sources/documents")).toBe(true);
  });
});
