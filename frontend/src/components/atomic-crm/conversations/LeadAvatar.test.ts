// Logic-level tests for LeadAvatar's fallback state machine.
//
// LeadAvatar renders an <img> when resolveAvatarSrc returns a string, and the
// UserRound icon otherwise. The pure derivation is extracted so the fallback
// logic (no src → icon; src present → img; img failed → icon) is testable
// without a browser render — matching the project convention of logic tests
// over DOM render tests (full render behaviour is covered by typecheck +
// Playwright).

import { describe, expect, it } from "vitest";

import { LeadAvatar, resolveAvatarSrc } from "./LeadAvatar";

describe("resolveAvatarSrc", () => {
  it("returns the src when present and the image has not failed", () => {
    expect(resolveAvatarSrc("https://zalo.me/a.jpg", false)).toBe(
      "https://zalo.me/a.jpg",
    );
  });

  it("returns null when src is absent (icon fallback)", () => {
    expect(resolveAvatarSrc(undefined, false)).toBeNull();
    expect(resolveAvatarSrc(null, false)).toBeNull();
    expect(resolveAvatarSrc("", false)).toBeNull();
  });

  it("returns null when the image failed to load (icon fallback)", () => {
    // This is the broken-image case: even though src is non-empty, the avatar
    // must fall back to the icon so expired/404 Zalo URLs don't leave a blank.
    expect(resolveAvatarSrc("https://expired.invalid/a.jpg", true)).toBeNull();
  });
});

describe("LeadAvatar", () => {
  it("is a function component accepting the documented props", () => {
    expect(typeof LeadAvatar).toBe("function");
  });
});
