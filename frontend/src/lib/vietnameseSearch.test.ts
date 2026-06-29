import { describe, expect, it } from "vitest";

import {
  normalizeVietnameseSearchText,
  slugifyVietnamese,
  vietnameseSearchIncludes,
  vietnameseSearchKey,
} from "./vietnameseSearch";

describe("Vietnamese search helpers", () => {
  it("matches Vietnamese names when the query omits accents", () => {
    expect(vietnameseSearchIncludes("Lý Hoa Linh", "Ly Hoa Linh")).toBe(true);
  });

  it("normalizes Vietnamese d with stroke", () => {
    expect(normalizeVietnameseSearchText("Đặng Thị Dung")).toContain("dang");
    expect(vietnameseSearchIncludes("Đặng Thị Dung", "dang")).toBe(true);
  });

  it("builds searchable keys from mixed fields", () => {
    expect(vietnameseSearchKey("Dự án", "LG Display")).toContain(
      "du an lg display",
    );
  });

  it("creates stable ASCII slugs", () => {
    expect(slugifyVietnamese("Dự án Đặng Thị Dung")).toBe(
      "du-an-dang-thi-dung",
    );
  });
});
