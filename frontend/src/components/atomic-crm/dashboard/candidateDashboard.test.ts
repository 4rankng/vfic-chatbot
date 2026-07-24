import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiJsonMock } = vi.hoisted(() => ({
  apiJsonMock: vi.fn(),
}));
vi.mock("@/lib/apiClient", () => ({
  apiJson: apiJsonMock,
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
  zalo_id: `oa:user-${id}`,
  name: `Ứng viên ${id}`,
  phone,
  avatar_url: null,
  conversation_id: null,
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

  it("joins candidates to conversation profile data and removes entries without a mobile number", async () => {
    apiJsonMock.mockImplementation((url?: string) =>
      Promise.resolve(
        url?.startsWith("/api/v1/leads")
          ? {
              data: [
                candidate(1, "2026-07-18T03:00:00Z"),
                candidate(2, "2026-07-18T02:00:00Z", null),
              ],
              total: 2,
            }
          : {
              data: [
                {
                  id: "conversation-1",
                  zalo_chat_id: "oa:user-1",
                  zalo_channel: "oa",
                  contact: {
                    display_name: "Nguyễn Văn Một",
                    avatar_url: "https://example.com/avatar-1.jpg",
                  },
                },
              ],
              total: 1,
            },
      ),
    );

    const result = await fetchDashboardCandidates();

    expect(apiJsonMock).toHaveBeenCalledWith(
      "/api/v1/leads?page=1&per_page=200&sort=created_at&order=DESC",
    );
    expect(apiJsonMock).toHaveBeenCalledWith(
      "/api/v1/conversations/by-zalo-ids?ids=oa%3Auser-1",
    );
    expect(result).toEqual([
      expect.objectContaining({
        id: 1,
        name: "Nguyễn Văn Một",
        avatar_url: "https://example.com/avatar-1.jpg",
        conversation_id: "conversation-1",
      }),
    ]);
  });

  it("does not let a non-OA contact override lead profile identity", async () => {
    apiJsonMock.mockImplementation((url?: string) =>
      Promise.resolve(
        url?.startsWith("/api/v1/leads")
          ? {
              data: [candidate(1, "2026-07-18T03:00:00Z")],
              total: 1,
            }
          : {
              data: [
                {
                  id: "bot-conversation",
                  zalo_chat_id: "oa:user-1",
                  zalo_channel: "bot",
                  updated_at: "2026-07-18T04:00:00Z",
                  contact: {
                    display_name: "Nhãn không đáng tin",
                    avatar_url: "https://example.com/non-oa-avatar.jpg",
                  },
                },
              ],
              total: 1,
            },
      ),
    );

    await expect(fetchDashboardCandidates()).resolves.toEqual([
      expect.objectContaining({
        name: "Ứng viên 1",
        avatar_url: null,
        conversation_id: "bot-conversation",
      }),
    ]);
  });

  it("keeps a lead-only candidate static when no conversation identity exists", async () => {
    apiJsonMock.mockResolvedValue({
      data: [
        {
          ...candidate(3, "2026-07-18T03:00:00Z"),
          zalo_id: null,
          avatar_url: "https://example.com/lead-avatar.jpg",
        },
      ],
      total: 1,
    });

    await expect(fetchDashboardCandidates()).resolves.toEqual([
      expect.objectContaining({
        id: 3,
        avatar_url: "https://example.com/lead-avatar.jpg",
        conversation_id: null,
      }),
    ]);
    expect(apiJsonMock).toHaveBeenCalledTimes(1);
  });
});
