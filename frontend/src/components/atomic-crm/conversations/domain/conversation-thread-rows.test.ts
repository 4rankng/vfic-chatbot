// Boundary contract of the thread's message grouping.
//
// The thread renders one memoized bubble per row, and the row's `kind` and
// `isGrouped` are what pick its variant and whether it keeps an avatar. These
// tests pin the four boundary shapes the thread actually hits: an empty
// conversation, a lone message, a same-kind run that crosses midnight, and a
// run interrupted by another kind.

import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "./conversation-message";
import {
  classifyConversationMessage,
  groupConversationMessages,
} from "./conversation-thread-rows";

const message = (
  overrides: Partial<ConversationMessage>,
): ConversationMessage => ({
  id: "message-1",
  conversation_id: "conversation-1",
  type: "outbound",
  content: "Chào bạn",
  data: { recruiter_id: "recruiter-1" },
  created_at: "2026-09-26T10:00:00.000Z",
  ...overrides,
});

const candidate = (overrides: Partial<ConversationMessage> = {}) =>
  message({ type: "inbound", data: null, ...overrides });

const bot = (overrides: Partial<ConversationMessage> = {}) =>
  message({ type: "outbound", data: null, ...overrides });

describe("groupConversationMessages", () => {
  it("produces no rows for a conversation with no messages", () => {
    expect(groupConversationMessages([])).toEqual([]);
  });

  it("starts a lone message ungrouped", () => {
    const only = candidate({ id: "1" });

    expect(groupConversationMessages([only])).toEqual([
      { message: only, kind: "user", isGrouped: false },
    ]);
  });

  it("keeps a same-kind run grouped across midnight", () => {
    const rows = groupConversationMessages([
      bot({ id: "1", created_at: "2026-09-26T23:59:00.000Z" }),
      bot({ id: "2", created_at: "2026-09-27T00:01:00.000Z" }),
      candidate({ id: "3", created_at: "2026-09-27T00:02:00.000Z" }),
    ]);

    expect(rows.map((row) => row.kind)).toEqual(["bot", "bot", "user"]);
    expect(rows.map((row) => row.isGrouped)).toEqual([false, true, false]);
  });

  it("breaks a run wherever the kind changes and does not rejoin it after one", () => {
    const rows = groupConversationMessages([
      candidate({ id: "1" }),
      candidate({ id: "2" }),
      bot({ id: "3" }),
      candidate({ id: "4" }),
    ]);

    expect(rows.map((row) => row.isGrouped)).toEqual([
      false,
      true,
      false,
      false,
    ]);
  });
});

describe("classifyConversationMessage", () => {
  it("picks the variant from the message direction", () => {
    expect(classifyConversationMessage(candidate({ id: "1" }))).toBe("user");
    expect(
      classifyConversationMessage(
        message({ id: "2", data: { recruiter_id: "recruiter-7" } }),
      ),
    ).toBe("agent");
    expect(classifyConversationMessage(bot({ id: "3" }))).toBe("bot");
    expect(
      classifyConversationMessage(message({ id: "4", type: "system" })),
    ).toBe("system");
  });

  it("keeps an inbound message on the candidate side even when it carries a recruiter id", () => {
    expect(
      classifyConversationMessage(
        message({
          id: "1",
          type: "inbound",
          data: { recruiter_id: "recruiter-7" },
        }),
      ),
    ).toBe("user");
  });
});
