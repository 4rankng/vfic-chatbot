import { describe, expect, it } from "vitest";

import type { CompiledDestination } from "../capabilities/types";
import {
  getMobileTabDestinations,
  getWorkspaceDestination,
  getWorkspaceDestinations,
  getWorkspaceSections,
  MOBILE_TAB_LIMIT,
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
    ).toEqual(["operations", "team", "system"]);
  });

  it("normalizes hash and search variants to one path", () => {
    expect(normalizeWorkspacePath("#/projects?tab=1")).toBe("/projects");
    expect(normalizeWorkspacePath("/conversations?id=7")).toBe(
      "/conversations",
    );
    expect(normalizeWorkspacePath("")).toBe("/");
    expect(normalizeWorkspacePath("projects")).toBe("/projects");
  });

  it("caps the mobile tab bar at the Material 3–5 band, in declaration order", () => {
    const crowded: readonly CompiledDestination[] = [
      ...navigation,
      destination("projects", "operations"),
      destination("performance", "system", { roles: ["admin"] }),
    ];

    // An admin sees the first five primary destinations; the rest stay in
    // the slideout drawer.
    expect(
      getMobileTabDestinations("admin", crowded).map(({ id }) => id),
    ).toEqual(["overview", "messages", "users", "settings", "projects"]);
    expect(getMobileTabDestinations("admin", crowded)).toHaveLength(
      MOBILE_TAB_LIMIT,
    );

    // A recruiter has fewer than five destinations — all of them fit.
    expect(
      getMobileTabDestinations("recruiter", crowded).map(({ id }) => id),
    ).toEqual(["overview", "messages", "projects"]);
  });

  it("deep-links the inbox badge to the server-filtered reply queue", () => {
    const messages = navigation[1];
    expect(getWorkspaceDestination(messages, 3)).toBe(
      "/messages?needs_attention=true",
    );
    expect(getWorkspaceDestination(messages, 0)).toBe("/messages");
    expect(getWorkspaceDestination(navigation[2], 3)).toBe("/users");
  });
});
