import { describe, expect, it } from "vitest";

import { getConversationListServerFilter } from "./conversation-list-filters";

describe("getConversationListServerFilter", () => {
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
});
