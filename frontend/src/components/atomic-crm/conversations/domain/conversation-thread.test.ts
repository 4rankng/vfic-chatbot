import { describe, expect, it } from "vitest";

import type { Message } from "../../types";
import {
  findConfirmedOptimisticIds,
  isUnseenWorthyArrival,
  keepConversationMessages,
} from "./conversation-thread";

const message = (overrides: Partial<Message>): Message => ({
  id: "message-1",
  zalo_message_id: "message-1",
  conversation_id: "conversation-1",
  type: "outbound",
  content: "xin chao",
  data: { recruiter_id: "recruiter-1" },
  created_at: "2026-07-23T10:00:00.000Z",
  ...overrides,
});

describe("conversation thread domain rules", () => {
  it("filters mixed messages to the active conversation", () => {
    expect(
      keepConversationMessages(
        [
          message({ id: "1", conversation_id: "conversation-1" }),
          message({ id: "2", conversation_id: "conversation-2" }),
        ],
        "conversation-1",
      ).map((entry) => entry.id),
    ).toEqual(["1"]);
  });

  it("matches a confirmed reply back to its pending optimistic message", () => {
    const pending = message({
      id: "optimistic-1",
      created_at: "2026-07-23T10:00:00.000Z",
    });
    const confirmed = message({
      id: "server-1",
      created_at: "2026-07-23T10:00:05.000Z",
    });

    expect(
      findConfirmedOptimisticIds({
        confirmedMessages: [confirmed],
        pendingMessages: [pending],
      }),
    ).toEqual(["optimistic-1"]);
  });

  it("only marks unseen arrivals for inbound, bot, or other-recruiter messages", () => {
    expect(
      isUnseenWorthyArrival(
        message({ id: "optimistic-1", type: "outbound" }),
        "recruiter-1",
      ),
    ).toBe(false);
    expect(
      isUnseenWorthyArrival(
        message({ id: "server-1", type: "outbound" }),
        "recruiter-1",
      ),
    ).toBe(false);
    expect(
      isUnseenWorthyArrival(
        message({
          id: "server-2",
          type: "outbound",
          data: { recruiter_id: "recruiter-2" },
        }),
        "recruiter-1",
      ),
    ).toBe(true);
    expect(
      isUnseenWorthyArrival(
        message({
          id: "server-3",
          type: "outbound",
          data: { recruiter_id: null },
        }),
        "recruiter-1",
      ),
    ).toBe(true);
    expect(
      isUnseenWorthyArrival(
        message({ id: "server-4", type: "inbound", data: { recruiter_id: null } }),
        "recruiter-1",
      ),
    ).toBe(true);
  });
});
