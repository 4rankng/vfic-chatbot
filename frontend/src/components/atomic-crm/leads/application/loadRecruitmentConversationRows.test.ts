import { describe, expect, it } from "vitest";

import type { Conversation, Lead } from "../../types";
import { loadRecruitmentConversationRows, mapLeadsByZaloId } from "./loadRecruitmentConversationRows";

const conversation = (overrides: Partial<Conversation> = {}): Conversation => ({
  id: "conv-1",
  mode: "bot",
  last_inbound_at: null,
  assigned_recruiter_id: null,
  created_at: "2026-07-23T00:00:00Z",
  updated_at: "2026-07-23T00:00:00Z",
  zalo_channel: "oa",
  zalo_chat_id: "oa:user-1",
  contact: {
    id: "contact-1",
    display_name: "Bé Gấu",
    avatar_url: "https://example.test/avatar.jpg",
  },
  ...overrides,
});

const lead = (overrides: Partial<Lead> = {}): Lead => ({
  id: 1,
  zalo_id: "oa:user-1",
  name: "Nguyễn Văn An",
  phone: "0900000001",
  desired_job: "Tài xế",
  expected_salary: "",
  lead_score: "warm",
  lead_stage: "NEW",
  created_at: "2026-07-23T00:00:00Z",
  updated_at: "2026-07-23T00:00:00Z",
  ...overrides,
});

describe("mapLeadsByZaloId", () => {
  it("keeps the first lead for each zalo id", () => {
    const first = lead({ id: 1, zalo_id: "oa:user-1" });
    const second = lead({ id: 2, zalo_id: "oa:user-1", name: "Khác" });

    const mapped = mapLeadsByZaloId([first, second]);

    expect(mapped.get("oa:user-1")).toEqual(first);
  });
});

describe("loadRecruitmentConversationRows", () => {
  it("loads one lead batch and builds row presentation with search text", async () => {
    const listByZaloIds = async () => [lead()];

    const rows = await loadRecruitmentConversationRows(
      [conversation()],
      { listByZaloIds },
    );

    expect(rows.get("conv-1")).toEqual({
      lead: lead(),
      presentation: {
        displayName: "Nguyễn Văn An",
        subtitle: "0900000001",
        avatarUrl: "https://example.test/avatar.jpg",
        oaProfileName: "Bé Gấu",
        searchText: "oa:user-1 Nguyễn Văn An Bé Gấu 0900000001 Tài xế",
      },
    });
  });

  it("returns an empty map when there are no zalo ids to fetch", async () => {
    const rows = await loadRecruitmentConversationRows(
      [conversation({ id: "conv-2", zalo_chat_id: null })],
      {
        listByZaloIds: async () => {
          throw new Error("should not fetch");
        },
      },
    );

    expect(rows.size).toBe(0);
  });
});
