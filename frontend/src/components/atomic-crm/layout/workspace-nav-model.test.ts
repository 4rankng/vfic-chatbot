import { describe, expect, it } from "vitest";

import type { CompiledDestination } from "../capabilities/types";
import {
  getWorkspaceDestination,
  getWorkspaceDestinations,
  getWorkspaceSections,
  normalizeWorkspacePath,
} from "./workspace-nav-model";

const destination = (
  id: string,
  section: CompiledDestination["section"],
  options: Partial<CompiledDestination> = {},
): CompiledDestination => ({
  id,
  label: id,
  to: `/${id}`,
  Icon: (() => null) as unknown as CompiledDestination["Icon"],
  section,
  isActive: (path: string) => path.startsWith(`/${id}`),
  ...options,
});

const navigation: readonly CompiledDestination[] = [
  destination("overview", "operations", { to: "/" }),
  destination("messages", "operations"),
  destination("knowledge_sources", "knowledge", { roles: ["admin"] }),
  destination("users", "team", { roles: ["admin"] }),
  destination("settings", "system", { roles: ["admin"] }),
];

describe("workspace navigation model", () => {
  it("keeps a recruiter out of admin-only destinations", () => {
    expect(
      getWorkspaceDestinations("recruiter", navigation).map(({ id }) => id),
    ).toEqual(["overview", "messages"]);
  });

  it("groups destinations into ordered sections and drops empty ones", () => {
    expect(
      getWorkspaceSections("recruiter", navigation).map((section) => [
        section.id,
        section.items.map(({ id }) => id),
      ]),
    ).toEqual([["operations", ["overview", "messages"]]]);

    expect(
      getWorkspaceSections("admin", navigation).map((section) => section.id),
    ).toEqual(["operations", "knowledge", "team", "system"]);
  });

  it("normalizes hash and search variants to one path", () => {
    expect(normalizeWorkspacePath("#/projects?tab=1")).toBe("/projects");
    expect(normalizeWorkspacePath("/conversations?id=7")).toBe(
      "/conversations",
    );
    expect(normalizeWorkspacePath("")).toBe("/");
    expect(normalizeWorkspacePath("projects")).toBe("/projects");
  });

  it("deep-links the inbox badge to the server-filtered reply queue", () => {
    const messages = navigation[1];
    expect(getWorkspaceDestination(messages, 3)).toBe(
      "/messages?needs_attention=true",
    );
    expect(getWorkspaceDestination(messages, 0)).toBe("/messages");
    expect(getWorkspaceDestination(navigation[2], 3)).toBe(
      "/knowledge_sources",
    );
  });
});
