import { describe, expect, it } from "vitest";
import { getZaloUserId } from "./domain/conversation-display";

describe("getZaloUserId", () => {
  it("removes the internal OA namespace before showing the recipient ID", () => {
    expect(getZaloUserId("oa:123456789", "oa")).toBe("123456789");
  });

  it("preserves bot-platform IDs", () => {
    expect(getZaloUserId("123456789", "bot")).toBe("123456789");
  });
});
