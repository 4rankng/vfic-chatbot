import { describe, expect, it } from "vitest";

import type { Conversation, Lead } from "../../types";
import {
  loadRecruitmentConversationRows,
  mapLeadsByContactId,
  mapLeadsByZaloId,
} from "./loadRecruitmentConversationRows";

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

const messengerConversation = (overrides: Partial<Conversation> = {}) =>
  conversation({
    id: "conv-2",
    zalo_chat_id: null,
    contact_id: "contact-2",
    contact: {
      id: "contact-2",
      display_name: null,
      avatar_url: null,
    },
    channel_identity: {
      id: "identity-2",
      provider: "facebook_messenger",
      account_key: "page-1",
      external_id: "987654321",
    },
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

describe("mapLeadsByContactId", () => {
  it("keys contact-id leads and skips those without one", () => {
    const keyed = lead({
      id: 7,
      contact_id: "contact-2",
      name: "Phạm Văn Thành",
    });
    const unkeyed = lead({ id: 8, contact_id: null, name: "Không có contact" });

    const mapped = mapLeadsByContactId([keyed, unkeyed]);

    expect(mapped.get("contact-2")).toEqual(keyed);
    expect(mapped.size).toBe(1);
  });
});

describe("loadRecruitmentConversationRows", () => {
  it("loads one lead batch and builds row presentation with search text", async () => {
    const listByZaloIds = async () => [lead()];

    const rows = await loadRecruitmentConversationRows([conversation()], {
      listByZaloIds,
      listByContactIds: async () => [],
    });

    expect(rows.get("conv-1")).toEqual({
      lead: lead(),
      presentation: {
        displayName: "Nguyễn Văn An",
        subtitle: "0900000001",
        avatarUrl: "https://example.test/avatar.jpg",
        channelProfileName: "Bé Gấu",
        searchText: "oa:user-1 Nguyễn Văn An Bé Gấu 0900000001 Tài xế",
      },
    });
  });

  it("resolves a Messenger row's lead by contact id, so the name is shown", async () => {
    // The regression: Messenger rows carry no zalo_chat_id, so a zalo-only
    // lookup never resolved their lead and the row fell back to the PSID tail
    // ("Ứng viên · 4321") even though the lead had a name all along. This is
    // also why the row cannot rely on the channel profile: Messenger profile
    // names are unavailable to the app, so contact.display_name is null.
    const listByContactIds = async (ids: string[]) => {
      expect(ids).toEqual(["contact-2"]);
      return [
        lead({
          id: 9734,
          zalo_id: "",
          contact_id: "contact-2",
          name: "Phạm Văn Thành",
        }),
      ];
    };

    const rows = await loadRecruitmentConversationRows(
      [messengerConversation()],
      {
        listByZaloIds: async () => {
          throw new Error("a Messenger row has no zalo id to fetch");
        },
        listByContactIds,
      },
    );

    expect(rows.get("conv-2")?.presentation).toMatchObject({
      displayName: "Phạm Văn Thành",
      subtitle: "0900000001",
    });
  });

  it("falls back to the channel label when a Messenger lead has no name yet", async () => {
    const rows = await loadRecruitmentConversationRows(
      [
        messengerConversation({
          contact: {
            id: "contact-2",
            display_name: "Frank Ng",
            avatar_url: "https://example.test/messenger.jpg",
          },
        }),
      ],
      {
        listByZaloIds: async () => {
          throw new Error("a Messenger row has no zalo id to fetch");
        },
        listByContactIds: async () => [],
      },
    );

    expect(rows.get("conv-2")?.presentation).toMatchObject({
      displayName: "Frank Ng",
      avatarUrl: "https://example.test/messenger.jpg",
    });
  });
});
