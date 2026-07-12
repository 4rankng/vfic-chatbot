import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";

const apiJsonMock = vi.fn();
vi.mock("../providers/rest/api", () => ({
  apiJson: (...args: unknown[]) => apiJsonMock(...args),
}));

import { fetchAttentionDashboard } from "./attentionDashboard";

import {
  ATTENTION_PREVIEW_LIMIT,
  ATTENTION_QUERY_KEY,
  ATTENTION_REASONS,
  COUNTER_LABELS,
  REASON_LABELS,
  counterForReason,
  formatElapsed,
  isAttentionReason,
  reasonLabelForQueue,
} from "./attentionDashboard";

describe("REASON_LABELS", () => {
  it("provides a Vietnamese label for every backend reason enum", () => {
    for (const reason of ATTENTION_REASONS) {
      const label = REASON_LABELS[reason];
      expect(typeof label, `label for ${reason}`).toBe("string");
      expect(label.length, `label for ${reason} is non-empty`).toBeGreaterThan(
        0,
      );
    }
  });

  it("exposes exactly the nine Phase 1 reasons with no extras", () => {
    expect(ATTENTION_REASONS).toEqual([
      "DELIVERY_REVIEW",
      "HUMAN_ESCALATION",
      "REPLY_OVERDUE",
      "FOLLOWUP_OVERDUE",
      "WAITING_REPLY",
      "PRIORITY_NO_ACTION",
      "FOLLOWUP_TODAY",
      "UNREAD",
      "STALLED",
    ]);
    expect(Object.keys(REASON_LABELS).sort()).toEqual(
      [...ATTENTION_REASONS].sort(),
    );
  });

  it("uses an action-oriented label for priority candidates needing outreach", () => {
    expect(REASON_LABELS.PRIORITY_NO_ACTION).toBe(
      "Ứng viên ưu tiên cần liên hệ",
    );
  });

  it("omits the duplicate priority reason from the today queue", () => {
    expect(reasonLabelForQueue("PRIORITY_NO_ACTION", "today")).toBeNull();
    expect(reasonLabelForQueue("PRIORITY_NO_ACTION", "immediate")).toBe(
      "Ứng viên ưu tiên cần liên hệ",
    );
    expect(reasonLabelForQueue("FOLLOWUP_TODAY", "today")).toBe(
      "Theo dõi hôm nay",
    );
  });
});

describe("COUNTER_LABELS", () => {
  it("labels exactly the five plan counters in Vietnamese", () => {
    expect(Object.keys(COUNTER_LABELS).sort()).toEqual(
      ["due_today", "needs_reply", "overdue", "priority", "unread"].sort(),
    );
    expect(COUNTER_LABELS.needs_reply).toBe("Cần phản hồi");
    expect(COUNTER_LABELS.overdue).toBe("Quá hạn");
    expect(COUNTER_LABELS.due_today).toBe("Theo dõi hôm nay");
    expect(COUNTER_LABELS.priority).toBe("Ứng viên ưu tiên");
    expect(COUNTER_LABELS.unread).toBe("Chưa đọc");
  });
});

describe("counterForReason", () => {
  // Mirrors the backend AttentionCounters docstring.
  it("routes needs-reply reasons to needs_reply (REPLY_OVERDUE picks the more urgent bucket)", () => {
    expect(counterForReason("WAITING_REPLY")).toBe("needs_reply");
    expect(counterForReason("HUMAN_ESCALATION")).toBe("needs_reply");
    expect(counterForReason("REPLY_OVERDUE")).toBe("needs_reply");
  });

  it("routes the follow-up-overdue reason to overdue", () => {
    expect(counterForReason("FOLLOWUP_OVERDUE")).toBe("overdue");
  });

  it("routes the follow-up-today reason to due_today", () => {
    expect(counterForReason("FOLLOWUP_TODAY")).toBe("due_today");
  });

  it("routes priority reasons to priority", () => {
    expect(counterForReason("PRIORITY_NO_ACTION")).toBe("priority");
    expect(counterForReason("DELIVERY_REVIEW")).toBe("priority");
    expect(counterForReason("STALLED")).toBe("priority");
  });

  it("routes unread to unread", () => {
    expect(counterForReason("UNREAD")).toBe("unread");
  });

  it("covers every reason (no fallthrough)", () => {
    for (const reason of ATTENTION_REASONS) {
      expect(counterForReason(reason), `counter for ${reason}`).toMatch(
        /^(needs_reply|overdue|due_today|priority|unread)$/,
      );
    }
  });
});

describe("isAttentionReason", () => {
  // Guards the `?reason=` URL param at the system boundary before it is
  // forwarded to the data provider as a server filter (BLOCKER #1).
  it("accepts every backend reason enum", () => {
    for (const reason of ATTENTION_REASONS) {
      expect(isAttentionReason(reason), `isAttentionReason(${reason})`).toBe(
        true,
      );
    }
  });

  it("rejects null/undefined/empty", () => {
    expect(isAttentionReason(null)).toBe(false);
    expect(isAttentionReason(undefined)).toBe(false);
    expect(isAttentionReason("")).toBe(false);
  });

  it("rejects unknown or case-variant values (defensive — never reaches the backend)", () => {
    expect(isAttentionReason("NOT_A_REASON")).toBe(false);
    // The backend enum is uppercase; lowercase must NOT slip through.
    expect(isAttentionReason("reply_overdue")).toBe(false);
    expect(isAttentionReason("REPLY_OVERDUE ")).toBe(false);
  });

  it("narrows the type so the value is usable as an AttentionReason", () => {
    const value: string | null = "REPLY_OVERDUE";
    if (isAttentionReason(value)) {
      // Assignment to an AttentionReason-typed const proves the narrowing.
      const asReason: (typeof ATTENTION_REASONS)[number] = value;
      expect(asReason).toBe("REPLY_OVERDUE");
    } else {
      throw new Error("should have narrowed");
    }
  });
});

describe("formatElapsed", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns empty string for unparseable input", () => {
    expect(formatElapsed("not-a-date")).toBe("");
  });

  it("returns vừa xong for sub-minute deltas (no '0 phút' noise)", () => {
    vi.setSystemTime(new Date("2026-07-12T10:00:00Z"));
    expect(formatElapsed("2026-07-12T10:00:30Z")).toBe("vừa xong");
  });

  it("formats minutes", () => {
    vi.setSystemTime(new Date("2026-07-12T10:00:00Z"));
    expect(formatElapsed("2026-07-12T09:55:00Z")).toBe("5 phút");
  });

  it("formats hours", () => {
    vi.setSystemTime(new Date("2026-07-12T10:00:00Z"));
    expect(formatElapsed("2026-07-12T08:00:00Z")).toBe("2 giờ");
  });

  it("formats days under 28", () => {
    vi.setSystemTime(new Date("2026-07-12T10:00:00Z"));
    expect(formatElapsed("2026-07-09T10:00:00Z")).toBe("3 ngày");
  });

  it("never produces a negative count (future timestamps clamp to vừa xong)", () => {
    vi.setSystemTime(new Date("2026-07-12T10:00:00Z"));
    expect(formatElapsed("2026-07-12T11:00:00Z")).toBe("vừa xong");
  });
});

describe("fetchAttentionDashboard + query key", () => {
  beforeEach(() => {
    apiJsonMock.mockReset();
  });

  it("exposes a stable query key array", () => {
    expect(ATTENTION_QUERY_KEY).toEqual(["dashboard-attention"]);
  });

  it("calls apiJson against the attention endpoint and unwraps the payload", async () => {
    const payload = {
      updated_at: "2026-07-12T10:00:00Z",
      counters: {
        needs_reply: 3,
        overdue: 1,
        due_today: 2,
        priority: 0,
        unread: 5,
      },
      immediate: [],
      today: [],
    };
    apiJsonMock.mockResolvedValue(payload);
    const result = await fetchAttentionDashboard();
    expect(apiJsonMock).toHaveBeenCalledWith("/api/v1/dashboard/attention");
    expect(result.counters.needs_reply).toBe(3);
    expect(result.counters.unread).toBe(5);
    expect(result.updated_at).toBe("2026-07-12T10:00:00Z");
  });
});

describe("ATTENTION_PREVIEW_LIMIT", () => {
  it("matches the backend bounded preview size", () => {
    expect(ATTENTION_PREVIEW_LIMIT).toBe(8);
  });
});
