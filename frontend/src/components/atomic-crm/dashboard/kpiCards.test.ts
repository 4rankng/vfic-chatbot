import { describe, expect, it } from "vitest";

import {
  buildKpiCards,
  KPI_WINDOW_DAYS,
  type KpiCard,
  type KpiLeadRow,
} from "./kpiCards";

const NOW = new Date("2026-10-21T12:00:00+07:00");

const row = (daysAgo: number, stage: string | null = "NEW"): KpiLeadRow => {
  const created = new Date(NOW);
  created.setDate(created.getDate() - daysAgo);
  return { created_at: created.toISOString(), lead_stage: stage };
};

const METRICS = {
  total_leads: 84,
  hired_rate: 25,
  open_conversations: 7,
  unread_conversation_count: 2,
  stage_breakdown: [
    { value: "NEW", count: 34, percentage: 40 },
    { value: "CONTACTING", count: 29, percentage: 35 },
    { value: "REGISTERED", count: 21, percentage: 25 },
    { value: "SKIPPED", count: 0, percentage: 0 },
  ],
};

const card = (cards: KpiCard[], id: string): KpiCard => {
  const found = cards.find((c) => c.id === id);
  if (!found) throw new Error(`missing card ${id}`);
  return found;
};

describe("buildKpiCards", () => {
  const leads: KpiLeadRow[] = [
    // Current 7-day window: 4 new, 2 already REGISTERED.
    row(1, "CONTACTING"),
    row(2, "REGISTERED"),
    row(3, "NEW"),
    row(5, "REGISTERED"),
    // Previous 7-day window: 2 new, 0 REGISTERED.
    row(8, "CONTACTING"),
    row(11, "SKIPPED"),
    // Older coverage tail so both windows are fully observed.
    row(20, "REGISTERED"),
  ];

  it("orders the four cards pipeline → new leads → conversion → open conversations", () => {
    const cards = buildKpiCards({ metrics: METRICS, leads, now: NOW });
    expect(cards.map((c) => c.id)).toEqual([
      "pipeline",
      "new-leads",
      "conversion",
      "open-conversations",
    ]);
  });

  it("marks the pipeline card as the dark headline with the stage mix caption", () => {
    const pipeline = card(
      buildKpiCards({ metrics: METRICS, leads, now: NOW }),
      "pipeline",
    );
    expect(pipeline.emphasis).toBe("headline");
    expect(pipeline.value).toBe("84");
    expect(pipeline.caption).toBe("Mới 34 · Đang liên hệ 29 · Đã đăng ký 21");
  });

  it("compares new leads against the previous window with a good/bad tone", () => {
    const newLeads = card(
      buildKpiCards({ metrics: METRICS, leads, now: NOW }),
      "new-leads",
    );
    // 4 new vs 2 previous = +100%.
    expect(newLeads.value).toBe("4");
    expect(newLeads.delta).toMatchObject({
      direction: "up",
      text: "+100%",
      tone: "good",
    });
  });

  it("flips the new-leads tone down when the period shrinks", () => {
    const shrinking = [...leads, row(9, "NEW"), row(10, "NEW"), row(12, "NEW")];
    const newLeads = card(
      buildKpiCards({ metrics: METRICS, leads: shrinking, now: NOW }),
      "new-leads",
    );
    expect(newLeads.delta?.direction).toBe("down");
    expect(newLeads.delta?.tone).toBe("bad");
  });

  it("converts cohort conversion movement into percentage points", () => {
    const conversion = card(
      buildKpiCards({ metrics: METRICS, leads, now: NOW }),
      "conversion",
    );
    // Current cohort: 2/4 = 50%; previous: 0/2 = 0% → +50 điểm.
    expect(conversion.value).toBe("25%");
    expect(conversion.delta).toMatchObject({
      direction: "up",
      text: "+50 điểm",
      tone: "good",
    });
  });

  it("answers open conversations with urgency counts instead of a delta", () => {
    const open = card(
      buildKpiCards({
        metrics: METRICS,
        counters: {
          needs_reply: 4,
          overdue: 2,
          due_today: 3,
          priority: 5,
          unread: 3,
        },
        leads,
        now: NOW,
      }),
      "open-conversations",
    );
    expect(open.value).toBe("7");
    expect(open.delta).toBeUndefined();
    expect(open.caption).toBe("4 cần phản hồi · 2 cần người xử lý");
  });

  it("reports a truncated trend as '—' when rows do not cover the previous window", () => {
    const shallow = [row(1), row(2), row(3)];
    const newLeads = card(
      buildKpiCards({ metrics: METRICS, leads: shallow, now: NOW }),
      "new-leads",
    );
    expect(newLeads.delta?.text).toBeNull();
    expect(newLeads.delta?.label).toBe(`so với ${KPI_WINDOW_DAYS} ngày trước`);
  });

  it("keeps a 'kỳ trước: 0' note instead of a fake infinite percent", () => {
    const onlyCurrent = [row(1), row(2), row(20)];
    const newLeads = card(
      buildKpiCards({ metrics: METRICS, leads: onlyCurrent, now: NOW }),
      "new-leads",
    );
    expect(newLeads.delta).toMatchObject({
      direction: "up",
      text: "kỳ trước: 0",
      tone: "good",
    });
  });

  it("renders zero-safe values when no metrics have arrived", () => {
    const cards = buildKpiCards({ leads: [], now: NOW });
    expect(card(cards, "pipeline").value).toBe("0");
    expect(card(cards, "conversion").value).toBe("0%");
    expect(card(cards, "open-conversations").caption).toBe(
      "Không có hội thoại chờ xử lý",
    );
  });
});
