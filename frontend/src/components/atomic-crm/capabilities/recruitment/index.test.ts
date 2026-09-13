import { describe, expect, it } from "vitest";

import { resolveRecruitmentProfile } from "./index";

describe("OA recruitment profile presentation", () => {
  const oaConversation = {
    zalo_channel: "oa" as const,
    zalo_chat_id: "oa:user-1234",
    contact: {
      id: "contact-1",
      display_name: "Bé Gấu",
      avatar_url: "https://example.test/oa-avatar.jpg",
    },
  };

  it("shows the exact OA label and avatar when no candidate name is confirmed", () => {
    expect(resolveRecruitmentProfile(oaConversation, undefined)).toEqual({
      displayName: "Bé Gấu",
      avatarUrl: "https://example.test/oa-avatar.jpg",
      oaProfileName: "Bé Gấu",
    });
  });

  it("keeps a confirmed candidate name ahead of the OA profile label", () => {
    expect(
      resolveRecruitmentProfile(oaConversation, {
        name: "Nguyễn Văn An",
        avatar_url: null,
      }).displayName,
    ).toBe("Nguyễn Văn An");
  });

  it("falls back to the channel photo when the lead has no avatar", () => {
    // The thread header shows the channel photo; the conversation list row
    // must not degrade to a generic placeholder for the same conversation.
    expect(
      resolveRecruitmentProfile(oaConversation, {
        name: "Nguyễn Văn An",
        avatar_url: null,
      }).avatarUrl,
    ).toBe("https://example.test/oa-avatar.jpg");
  });

  it("does not apply OA profile fallback to another channel", () => {
    expect(
      resolveRecruitmentProfile(
        { ...oaConversation, zalo_channel: "bot" },
        undefined,
      ).displayName,
    ).toBe("Ứng viên · 1234");
  });
});
