import { describe, expect, it } from "vitest";

import { replyFailureMessageKey } from "./reply-failure-messages";

describe("replyFailureMessageKey", () => {
  it("keys channel-naming failures to the Messenger catalog", () => {
    expect(
      replyFailureMessageKey("provider", {
        provider: "facebook_messenger",
        account_key: "486833177846024",
      }),
    ).toBe("resources.conversations.reply_messenger.provider");
    expect(
      replyFailureMessageKey("unavailable", {
        provider: "facebook_messenger",
        account_key: "486833177846024",
      }),
    ).toBe("resources.conversations.reply_messenger.unavailable");
  });

  it("keeps Zalo channels on the shared Zalo-worded catalog", () => {
    const zaloIdentity = {
      provider: "zalo_oa",
      account_key: "default:zalo_oa",
    };
    expect(replyFailureMessageKey("provider", zaloIdentity)).toBe(
      "resources.conversations.reply.provider",
    );
    expect(
      replyFailureMessageKey("unavailable", {
        provider: "zalo_oa",
        account_key: "tingting",
      }),
    ).toBe("resources.conversations.reply.unavailable");
  });

  it("keeps neutral statuses on the shared catalog for every channel", () => {
    const messengerIdentity = { provider: "facebook_messenger" };
    expect(replyFailureMessageKey("conflict", messengerIdentity)).toBe(
      "resources.conversations.reply.conflict",
    );
    expect(replyFailureMessageKey("network", messengerIdentity)).toBe(
      "resources.conversations.reply.network",
    );
    expect(replyFailureMessageKey("error", messengerIdentity)).toBe(
      "resources.conversations.reply.error",
    );
  });

  it("falls back to the shared catalog when the channel is unknown", () => {
    expect(replyFailureMessageKey("provider", null)).toBe(
      "resources.conversations.reply.provider",
    );
    expect(
      replyFailureMessageKey("provider", { provider: "carrier_pigeon" }),
    ).toBe("resources.conversations.reply.provider");
  });
});
