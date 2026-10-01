import { describe, expect, it } from "vitest";

import {
  conversationChannelLabel,
  conversationChannelShortLabel,
} from "../../types";
import { resolveConversationDisplayChannel } from "./conversation-channel-display";

describe("resolveConversationDisplayChannel", () => {
  it("keeps the Viet Phap (default) Zalo OA account on the zalo_oa channel", () => {
    expect(
      resolveConversationDisplayChannel({
        provider: "zalo_oa",
        account_key: "default:zalo_oa",
      }),
    ).toBe("zalo_oa");
    expect(
      conversationChannelShortLabel(
        resolveConversationDisplayChannel({
          provider: "zalo_oa",
          account_key: "default:zalo_oa",
        }),
      ),
    ).toBe("Zalo OA");
  });

  it("narrows the TingTing employee-support account to its own channel", () => {
    expect(
      resolveConversationDisplayChannel({
        provider: "zalo_oa",
        account_key: "tingting",
      }),
    ).toBe("tingting_oa");
    expect(
      conversationChannelLabel(
        resolveConversationDisplayChannel({
          provider: "zalo_oa",
          account_key: "tingting",
        }),
      ),
    ).toBe("TingTing OA");
    expect(
      conversationChannelShortLabel(
        resolveConversationDisplayChannel({
          provider: "zalo_oa",
          account_key: "tingting",
        }),
      ),
    ).toBe("TingTing OA");
  });

  it("trusts the server-derived display channel over the masked account key", () => {
    // Production responses mask account_key down to its tail, so the legacy
    // raw-key comparison can never match; the backend derives the badge
    // channel before masking (ConversationOut.channel_display).
    expect(
      resolveConversationDisplayChannel({
        provider: "zalo_oa",
        account_key: "*****ing",
        display_channel: "tingting_oa",
      }),
    ).toBe("tingting_oa");
    expect(
      resolveConversationDisplayChannel({
        provider: "zalo_oa",
        account_key: "*****ing",
        display_channel: "zalo_oa",
      }),
    ).toBe("zalo_oa");
  });

  it("treats a zalo_oa row without an account_key as the plain provider", () => {
    expect(resolveConversationDisplayChannel({ provider: "zalo_oa" })).toBe(
      "zalo_oa",
    );
    expect(
      resolveConversationDisplayChannel({
        provider: "zalo_oa",
        account_key: "",
      }),
    ).toBe("zalo_oa");
  });

  it("passes single-account channels through untouched", () => {
    expect(
      resolveConversationDisplayChannel({
        provider: "zalo_bot",
        account_key: "bot-1",
      }),
    ).toBe("zalo_bot");
    expect(
      resolveConversationDisplayChannel({
        provider: "facebook_messenger",
        account_key: "page-1",
      }),
    ).toBe("facebook_messenger");
  });

  it("resolves an already-narrowed tingting_oa identity to itself", () => {
    expect(
      resolveConversationDisplayChannel({
        provider: "tingting_oa",
        account_key: "tingting",
      }),
    ).toBe("tingting_oa");
  });

  it("falls back to null for missing or unknown identities", () => {
    expect(resolveConversationDisplayChannel(null)).toBeNull();
    expect(resolveConversationDisplayChannel(undefined)).toBeNull();
    expect(resolveConversationDisplayChannel({})).toBeNull();
    expect(
      resolveConversationDisplayChannel({ provider: "telegram" }),
    ).toBeNull();
    expect(resolveConversationDisplayChannel({ provider: "" })).toBeNull();
    // The null fallback reads as the neutral channel wording on every surface.
    expect(
      conversationChannelLabel(resolveConversationDisplayChannel(null)),
    ).toBe("Kênh khác");
  });
});
