import { describe, expect, it } from "vitest";

import {
  composePersonaMarkdown,
  getCompletedPersonaSectionCount,
  getPersonaAuthoredContentLength,
  parsePersonaMarkdown,
} from "./personaMarkdown";

describe("personaMarkdown", () => {
  it("parses known sections and keeps unknown markdown as extra content", () => {
    const parsed = parsePersonaMarkdown(
      [
        "### 1. Vai trò của tôi",
        "",
        "Tư vấn tuyển dụng",
        "",
        "### Ghi chú riêng",
        "",
        "Không chia sẻ ra ngoài",
      ].join("\n"),
    );

    expect(parsed.sections[0]).toBe("Tư vấn tuyển dụng");
    expect(parsed.extraMarkdown).toContain("### Ghi chú riêng");
  });

  it("re-composes authored sections and reports readiness metrics", () => {
    const markdown = composePersonaMarkdown([
      "Vai trò",
      "Người dùng",
      "",
      "",
      "",
      "",
      "",
    ]);

    expect(getCompletedPersonaSectionCount(markdown)).toBe(2);
    expect(getPersonaAuthoredContentLength(markdown)).toBeGreaterThan(0);
  });
});
