import { describe, expect, it } from "vitest";

import { formatCaseLifecycle } from "./CaseList";

describe("Case presentation", () => {
  it("localizes supported lifecycle values without inventing a fallback status", () => {
    expect(formatCaseLifecycle("OPEN")).toBe("Đang mở");
    expect(formatCaseLifecycle("CLOSED")).toBe("Đã đóng");
    expect(formatCaseLifecycle("CANCELLED")).toBe("Đã huỷ");
    expect(formatCaseLifecycle("UNKNOWN")).toBe("Không xác định");
  });
});
