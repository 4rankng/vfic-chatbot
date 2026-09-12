import { describe, expect, it } from "vitest";

import { buildDashboardStats } from "./dashboardMetrics";

describe("buildDashboardStats", () => {
  it("fills empty defaults when the payload is missing", () => {
    expect(buildDashboardStats(undefined, true)).toMatchObject({
      totalLeads: 0,
      stageBreakdown: [],
      knowledgeIngest: null,
      isPending: true,
    });
  });

  it("derives rates and preserves canonical stage ordering", () => {
    const stats = buildDashboardStats(
      {
        bot_run_count: 10,
        bot_sent_count: 7,
        bot_suppressed_count: 2,
        total_leads: 4,
        hired_count: 1,
        stage_breakdown: [
          { value: "REGISTERED", count: 2, percentage: 50 },
          { value: "NEW", count: 1, percentage: 25 },
        ],
        knowledge_ingest: {
          queue_depth: 3,
          failed_job_count: 1,
          worker_count: 2,
          processing_count: 4,
          stuck_count: 0,
          failed_document_count: 1,
          published_document_count: 8,
          stage_breakdown: [{ stage: "PUBLISHED", count: 8 }],
          recent_issues: [],
        },
      },
      false,
    );

    expect(stats.botSuccessRate).toBe(70);
    expect(stats.botSuppressionRate).toBe(0.2);
    expect(stats.hiredRate).toBe(25);
    expect(stats.stageBreakdown.map((item) => item.value)).toEqual([
      "NEW",
      "CONTACTING",
      "REGISTERED",
      "SKIPPED",
    ]);
    expect(
      stats.stageBreakdown.find((item) => item.value === "REGISTERED"),
    ).toMatchObject({ count: 2, percentage: 50 });
    expect(stats.knowledgeIngest?.queue_depth).toBe(3);
  });
});
