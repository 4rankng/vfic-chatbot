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

  it("does not apply OA profile fallback to another channel", () => {
    expect(
      resolveRecruitmentProfile(
        { ...oaConversation, zalo_channel: "bot" },
        undefined,
      ).displayName,
    ).toBe("Ứng viên · 1234");
  });
});
