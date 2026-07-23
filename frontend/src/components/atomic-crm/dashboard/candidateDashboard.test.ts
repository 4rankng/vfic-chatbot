import { beforeEach, describe, expect, it, vi } from "vitest";

const apiJsonMock = vi.fn();
vi.mock("@/lib/apiClient", () => ({
  apiJson: (...args: unknown[]) => apiJsonMock(...args),
}));

import {
  fetchDashboardCandidates,
  groupCandidatesByDay,
  type DashboardCandidate,
} from "./candidateDashboard";

const candidate = (
  id: number,
  createdAt: string,
  phone: string | null = `090000000${id}`,
): DashboardCandidate => ({
  id,
  name: `Ứng viên ${id}`,
  phone,
  desired_job: null,
  created_at: createdAt,
});

describe("groupCandidatesByDay", () => {
  it("keeps only candidates with a phone, newest first, grouped by Vietnam day", () => {
    const groups = groupCandidatesByDay(
      [
        candidate(1, "2026-07-17T16:30:00Z"),
        candidate(2, "2026-07-18T03:00:00Z"),
        candidate(3, "2026-07-18T01:00:00Z"),
        candidate(4, "2026-07-18T04:00:00Z", "  "),
      ],
      new Date("2026-07-18T05:00:00Z"),
    );

    expect(groups.map((group) => group.label)).toEqual(["Hôm nay", "Hôm qua"]);
    expect(groups[0]?.candidates.map((row) => row.id)).toEqual([2, 3]);
    expect(groups[1]?.candidates.map((row) => row.id)).toEqual([1]);
  });

  it("drops rows with invalid creation timestamps instead of creating a broken group", () => {
    expect(
      groupCandidatesByDay(
        [candidate(1, "not-a-date")],
        new Date("2026-07-18T05:00:00Z"),
      ),
    ).toEqual([]);
  });
});

describe("fetchDashboardCandidates", () => {
  beforeEach(() => apiJsonMock.mockReset());

  it("requests the newest candidates and removes entries without a mobile number", async () => {
    apiJsonMock.mockResolvedValue({
      data: [
        candidate(1, "2026-07-18T03:00:00Z"),
        candidate(2, "2026-07-18T02:00:00Z", null),
      ],
      total: 2,
    });

    const result = await fetchDashboardCandidates();

    expect(apiJsonMock).toHaveBeenCalledWith(
      "/api/v1/leads?page=1&per_page=200&sort=created_at&order=DESC",
    );
    expect(result.map((row) => row.id)).toEqual([1]);
  });
});
