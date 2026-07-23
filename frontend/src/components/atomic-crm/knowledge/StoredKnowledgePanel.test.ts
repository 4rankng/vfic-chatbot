import { describe, expect, it } from "vitest";

import {
  areEquivalentKnowledgeTexts,
  getKnowledgeUnitPreview,
  localizeKnowledgeText,
} from "./StoredKnowledgePanel";

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

describe("getKnowledgeUnitPreview", () => {
  it("prioritizes a human-readable question over raw source content", () => {
    expect(
      getKnowledgeUnitPreview({
        content: 'question: "Công ty có xe đưa đón không?"',
        questions: ["Công ty có xe đưa đón không?"],
        summary: null,
      }),
    ).toBe("Công ty có xe đưa đón không?");
  });

  it("falls back to the summary when no question is available", () => {
    expect(
      getKnowledgeUnitPreview({
        content: "Nội dung dài",
        questions: [],
        summary: "  Hỗ trợ xe đưa đón theo tuyến.  ",
      }),
    ).toBe("Hỗ trợ xe đưa đón theo tuyến.");
  });
});

describe("areEquivalentKnowledgeTexts", () => {
  it("detects duplicate text despite whitespace and letter case", () => {
    expect(
      areEquivalentKnowledgeTexts(
        "Công ty có xe đưa đón.",
        "  CÔNG TY   có xe đưa đón. ",
      ),
    ).toBe(true);
  });

  it("does not suppress genuinely different supporting text", () => {
    expect(
      areEquivalentKnowledgeTexts(
        "Tóm tắt chính sách",
        "Nội dung chính sách đầy đủ",
      ),
    ).toBe(false);
  });
});
