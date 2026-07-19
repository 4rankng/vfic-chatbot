import { describe, expect, it } from "vitest";

import { localizeKnowledgeText } from "./StoredKnowledgePanel";

describe("localizeKnowledgeText", () => {
  it("renders escaped and platform newlines as readable content", () => {
    expect(
      localizeKnowledgeText("  Dòng một\\nDòng hai\r\nDòng ba\\r\\nDòng bốn  "),
    ).toBe("Dòng một\nDòng hai\nDòng ba\nDòng bốn");
  });

  it("preserves ordinary knowledge text", () => {
    expect(localizeKnowledgeText("Lương: 12 triệu/tháng")).toBe(
      "Lương: 12 triệu/tháng",
    );
  });
});
