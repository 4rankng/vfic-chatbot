import { describe, expect, it } from "vitest";

import { canAccess } from "./canAccess";

const resources = new Set(["contacts", "cases", "conversations"]);

describe("canAccess", () => {
  it("keeps recruiter Contact list/edit access but hides administrator-only creation", () => {
    expect(canAccess("recruiter", { resource: "contacts", action: "list" }, resources)).toBe(true);
    expect(canAccess("recruiter", { resource: "contacts", action: "edit" }, resources)).toBe(true);
    expect(canAccess("recruiter", { resource: "contacts", action: "create" }, resources)).toBe(false);
    expect(canAccess("admin", { resource: "contacts", action: "create" }, resources)).toBe(true);
  });
});
