import { describe, expect, it } from "vitest";

import { resolveGoogleSheetGid } from "@/lib/vfic/knowledgeService";

describe("resolveGoogleSheetGid", () => {
  it("prefers #gid when query and fragment agree", () => {
    expect(
      resolveGoogleSheetGid(
        "https://docs.google.com/spreadsheets/d/demo/edit?gid=42#gid=42",
      ),
    ).toEqual({
      ok: true,
      gid: 42,
      source: "fragment",
    });
  });

  it("rejects links without an explicit gid", () => {
    expect(
      resolveGoogleSheetGid(
        "https://docs.google.com/spreadsheets/d/demo/edit",
      ),
    ).toMatchObject({
      ok: false,
      reason: "missing",
    });
  });

  it("rejects malformed gid values", () => {
    expect(
      resolveGoogleSheetGid(
        "https://docs.google.com/spreadsheets/d/demo/edit#gid=abc",
      ),
    ).toMatchObject({
      ok: false,
      reason: "invalid",
    });
  });

  it("uses the fragment gid when query and fragment differ", () => {
    expect(
      resolveGoogleSheetGid(
        "https://docs.google.com/spreadsheets/d/demo/edit?gid=7#gid=42",
      ),
    ).toEqual({
      ok: true,
      gid: 42,
      source: "fragment",
    });
  });

  it("rejects conflicting gids within the selected fragment source", () => {
    expect(
      resolveGoogleSheetGid(
        "https://docs.google.com/spreadsheets/d/demo/edit?gid=7#gid=42&gid=43",
      ),
    ).toMatchObject({ ok: false, reason: "conflict" });
  });

  it("ignores a malformed query gid when the fragment has a valid gid", () => {
    expect(
      resolveGoogleSheetGid(
        "https://docs.google.com/spreadsheets/d/demo/edit?gid=bad#gid=42",
      ),
    ).toEqual({ ok: true, gid: 42, source: "fragment" });
  });

  it("rejects gids outside the JavaScript safe integer range", () => {
    expect(
      resolveGoogleSheetGid(
        `https://docs.google.com/spreadsheets/d/demo/edit#gid=${Number.MAX_SAFE_INTEGER + 1}`,
      ),
    ).toMatchObject({
      ok: false,
      reason: "invalid",
    });
  });
});
