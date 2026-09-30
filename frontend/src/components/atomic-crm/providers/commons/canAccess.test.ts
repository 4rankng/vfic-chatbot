import { describe, expect, it } from "vitest";

import { canAccess } from "./canAccess";

const resources = new Set(["conversations", "projects"]);

describe("canAccess", () => {
  it("allows recruiters to use the recruitment workspace resources", () => {
    expect(
      canAccess(
        "recruiter",
        { resource: "conversations", action: "list" },
        resources,
      ),
    ).toBe(true);
    expect(
      canAccess(
        "recruiter",
        { resource: "projects", action: "edit" },
        resources,
      ),
    ).toBe(true);
    expect(
      canAccess("recruiter", { resource: "users", action: "list" }, resources),
    ).toBe(false);
  });
});
