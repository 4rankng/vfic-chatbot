import { describe, expect, it } from "vitest";

import {
  getChannelProviderSearchParams,
  getConversationListKey,
  getConversationListServerFilter,
  getEffectiveConversationChannelProvider,
} from "./domain/conversation-list-filters";

describe("getConversationListServerFilter", () => {
  // The former component-source pins (no count badge, no queue filters, no
  // tt-btn rows) are guarded as rendered output by the e2e inbox journey in
  // frontend/e2e/vfic.spec.ts, against the real backend.
  it("maps the Messages badge deep link to the authoritative reply queue", () => {
    expect(
      getConversationListServerFilter(
        new URLSearchParams("needs_attention=true"),
      ),
    ).toEqual({ needs_attention: true });
  });

  it("keeps an explicit attention reason ahead of the broad reply queue", () => {
    expect(
      getConversationListServerFilter(
        new URLSearchParams("reason=REPLY_OVERDUE&needs_attention=true"),
      ),
    ).toEqual({ reason: "REPLY_OVERDUE" });
  });

  it("keeps an unscoped inbox query cross-channel", () => {
    expect(
      getEffectiveConversationChannelProvider(new URLSearchParams()),
    ).toBeUndefined();
    expect(getConversationListServerFilter(new URLSearchParams())).toEqual({});
    expect(
      getEffectiveConversationChannelProvider(
        new URLSearchParams("channel_provider=messenger"),
      ),
    ).toBeUndefined();
  });

  it("treats API-unsupported channel scopes as unscoped", () => {
    expect(
      getConversationListServerFilter(
        new URLSearchParams("channel_provider=telegram"),
      ),
    ).toEqual({});
  });

  it("scopes the inbox to Messenger when that provider is selected", () => {
    expect(
      getConversationListServerFilter(
        new URLSearchParams("channel_provider=facebook_messenger"),
      ),
    ).toEqual({ channel_provider: "facebook_messenger" });
  });

  it("always composes a valid provider into normal and reason filters", () => {
    expect(
      getConversationListServerFilter(
        new URLSearchParams("channel_provider=zalo_oa"),
      ),
    ).toEqual({ channel_provider: "zalo_oa" });
    expect(
      getConversationListServerFilter(
        new URLSearchParams(
          "channel_provider=zalo_oa&reason=UNREAD&needs_attention=true",
        ),
      ),
    ).toEqual({ channel_provider: "zalo_oa", reason: "UNREAD" });
  });

  it("switches scope without losing attention context and clears the detail id", () => {
    const next = getChannelProviderSearchParams(
      new URLSearchParams(
        "channel_provider=zalo_bot&reason=STALLED&needs_attention=true&id=conversation-1",
      ),
      "zalo_oa",
    );
    expect(next.get("channel_provider")).toBe("zalo_oa");
    expect(next.get("reason")).toBe("STALLED");
    expect(next.get("needs_attention")).toBe("true");
    expect(next.has("id")).toBe(false);
  });

  it("uses provider and attention context in the list remount key", () => {
    expect(
      getConversationListKey({
        channel_provider: "zalo_oa",
        needs_attention: true,
      }),
    ).toBe("zalo_oa:needs-attention");
    expect(getConversationListKey({})).toBe("all:all");
  });
});
