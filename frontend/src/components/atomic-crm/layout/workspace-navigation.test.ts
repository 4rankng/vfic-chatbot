import { describe, expect, it } from "vitest";
import { Home } from "lucide-react";
import type { WorkspaceDestination } from "./workspace-navigation";

import {
  getWorkspaceDestinations,
  getWorkspaceDestination,
  getWorkspaceOverflowDestinations,
  normalizeWorkspacePath,
} from "./workspace-navigation";

const pathStartsWith = (prefix: string) => (path: string) =>
  path === prefix || path.startsWith(`${prefix}/`);
const destinations: WorkspaceDestination[] = [
  ["overview", "Tổng quan", "/", true, true],
  ["messages", "Tin nhắn", "/conversations", true, true],
  ["projects", "Dự án", "/projects", true, true],
  ["settings", "Cài đặt", "/settings", true, true],
  ["performance", "Hiệu suất", "/hieu-suat", true, false],
  ["account", "Tài khoản", "/profile", false, true],
].map(([id, label, to, rail, mobile]) => ({
  id: String(id),
  label: String(label),
  to: String(to),
  Icon: Home,
  roles:
    id === "settings" || id === "performance"
      ? (["admin"] as const)
      : undefined,
  rail: Boolean(rail),
  mobile: Boolean(mobile),
  isActive:
    id === "settings"
      ? (path: string) =>
          pathStartsWith("/settings")(path) ||
          pathStartsWith("/knowledge_sources")(path) ||
          pathStartsWith("/personas")(path)
      : id === "overview"
        ? (path: string) => path === "/"
        : pathStartsWith(String(to)),
}));

describe("workspace navigation", () => {
  it("normalizes browser and React Admin hash paths", () => {
    expect(normalizeWorkspacePath("#/conversations?id=42")).toBe(
      "/conversations",
    );
    expect(normalizeWorkspacePath("projects/123?tab=team")).toBe(
      "/projects/123",
    );
  });

  it("keeps account out of the desktop icon rail", () => {
    expect(
      getWorkspaceDestinations("admin", "rail", destinations).map(
        ({ label }) => label,
      ),
    ).toEqual(["Tổng quan", "Tin nhắn", "Dự án", "Cài đặt", "Hiệu suất"]);
  });

  it("keeps settings hidden from recruiters and account available on mobile", () => {
    expect(
      getWorkspaceDestinations("recruiter", "mobile", destinations).map(
        ({ label }) => label,
      ),
    ).toEqual(["Tổng quan", "Tin nhắn", "Dự án", "Tài khoản"]);
  });

  it("keeps the approved four-item mobile set for administrators", () => {
    expect(
      getWorkspaceDestinations("admin", "mobile", destinations).map(
        ({ label }) => label,
      ),
    ).toEqual(["Tổng quan", "Tin nhắn", "Dự án", "Cài đặt"]);
  });

  it("keeps desktop-only admin destinations reachable through mobile overflow", () => {
    expect(
      getWorkspaceOverflowDestinations("admin", destinations).map(
        ({ label }) => label,
      ),
    ).toEqual(["Hiệu suất", "Tài khoản"]);
    expect(getWorkspaceOverflowDestinations("recruiter", destinations)).toEqual(
      [],
    );
  });

  it("matches nested workspace routes", () => {
    const settings = getWorkspaceDestinations(
      "admin",
      "rail",
      destinations,
    ).find(({ id }) => id === "settings");
    expect(settings?.isActive("/knowledge_sources/documents")).toBe(true);
  });

  it("opens the server-filtered reply queue from a non-zero Messages badge", () => {
    const messages = destinations.find(({ id }) => id === "messages");
    expect(messages).toBeDefined();
    expect(getWorkspaceDestination(messages!, 1)).toBe(
      "/conversations?needs_attention=true",
    );
    expect(getWorkspaceDestination(messages!, 0)).toBe("/conversations");
  });
});
