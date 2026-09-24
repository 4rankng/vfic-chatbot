import { describe, expect, it, vi } from "vitest";

// socket.io-client must never be constructed by importing this capability: the
// module sits in the eager entry graph (static-recruitment-runtime ->
// reset-runtime-state -> App), so a module-scope realtime port would pull the
// Manager — and the realtime-vendor chunk — onto first paint. The spy throws so
// a regression fails loudly instead of silently costing entry bytes.
const socketIo = vi.hoisted(() => ({
  io: vi.fn(() => {
    throw new Error("socket.io-client Manager constructed at import time");
  }),
}));
vi.mock("socket.io-client", () => ({ io: socketIo.io }));

import { getRealtimeSocket } from "../../providers/realtime/realtime-socket";
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
      channelProfileName: "Bé Gấu",
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

  it("stays anonymous on Zalo Bot, which exposes no real profile", () => {
    expect(
      resolveRecruitmentProfile(
        { ...oaConversation, zalo_channel: "bot" },
        undefined,
      ).displayName,
    ).toBe("Ứng viên · 1234");
  });

  it("uses the Messenger profile even though zalo_channel defaults to bot", () => {
    // A Messenger row carries no zalo_chat_id and keeps the "bot" default, so
    // only the neutral provider can tell it apart from a Zalo Bot chat.
    const messengerConversation = {
      zalo_channel: "bot" as const,
      zalo_chat_id: null,
      contact: {
        id: "contact-2",
        display_name: "Frank Ng",
        avatar_url: "https://example.test/messenger.jpg",
      },
      channel_identity: {
        id: "identity-2",
        provider: "facebook_messenger",
        account_key: "page-1",
        external_id: "psid-987654",
      },
    };

    expect(resolveRecruitmentProfile(messengerConversation, undefined)).toEqual(
      {
        displayName: "Frank Ng",
        avatarUrl: "https://example.test/messenger.jpg",
        channelProfileName: "Frank Ng",
      },
    );
  });

  it("identifies an unnamed Messenger candidate by the neutral external id", () => {
    expect(
      resolveRecruitmentProfile(
        {
          zalo_channel: "bot" as const,
          zalo_chat_id: null,
          contact: null,
          channel_identity: {
            id: "identity-3",
            provider: "facebook_messenger",
            account_key: "page-1",
            external_id: "psid-987654",
          },
        },
        undefined,
      ).displayName,
    ).toBe("Ứng viên · 7654");
  });
});

describe("recruitment capability import cost", () => {
  it("does not construct the realtime socket when the module is imported", () => {
    // The import of ./index above is the observation: a module-scope
    // createLeadRealtimePort(getRealtimeSocket()) would have called io() here.
    expect(socketIo.io).not.toHaveBeenCalled();
  });

  it("still constructs the socket on demand, so the guard above can fail", () => {
    // Proves the spy is live: construction happens the moment the port asks for
    // a socket, which is exactly what importing the capability must not do.
    expect(() => getRealtimeSocket()).toThrow(
      "socket.io-client Manager constructed at import time",
    );
    expect(socketIo.io).toHaveBeenCalledOnce();
  });
});
