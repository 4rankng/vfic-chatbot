import { describe, expect, it } from "vitest";

import type { Message } from "../types";
import {
  mergeChronological,
  mergeRealtimePage,
} from "./useConversationRealtime";

const msg = (id: number): Message => ({
  id: String(id),
  zalo_message_id: String(id),
  conversation_id: "c1",
  type: id % 2 === 0 ? "outbound" : "inbound",
  content: `message ${id}`,
  data: { recruiter_id: null },
  created_at: `2026-06-29T00:00:${String(id).padStart(2, "0")}.000Z`,
});

describe("mergeChronological", () => {
  it("returns the same array reference when an incoming duplicate changes nothing", () => {
    const existing = [msg(10), msg(11)];
    const result = mergeChronological(existing, [{ ...existing[1] }]);

    expect(result).toBe(existing);
  });

  it("sorts merged messages by timestamp even when ids point the other way", () => {
    const older = {
      ...msg(2),
      created_at: "2026-06-29T01:22:00.000Z",
    };
    const newer = {
      ...msg(1),
      created_at: "2026-06-29T02:15:00.000Z",
    };

    const result = mergeChronological([], [newer, older]);

    expect(result.map((m) => m.id)).toEqual(["2", "1"]);
  });

  it("replaces a message when only delivery status changes", () => {
    const pending = {
      ...msg(20),
      delivery_status: "pending" as const,
    };
    const sent = {
      ...pending,
      delivery_status: "sent" as const,
    };

    const result = mergeChronological([pending], [sent]);

    expect(result).toHaveLength(1);
    expect(result[0]).not.toBe(pending);
    expect(result[0]).toBe(sent);
    expect(result[0].delivery_status).toBe("sent");
  });
});

describe("mergeRealtimePage", () => {
  it("normalizes an initial realtime page before any history is loaded", () => {
    const older = {
      ...msg(2),
      created_at: "2026-06-29T01:22:00.000Z",
    };
    const newer = {
      ...msg(1),
      created_at: "2026-06-29T02:15:00.000Z",
    };

    const result = mergeRealtimePage([], [newer, older]);

    expect(result.map((m) => m.id)).toEqual(["2", "1"]);
  });

  it("does not backfill older fetched rows into the current visible window", () => {
    const firstLoaded = msg(10);
    const current = [firstLoaded, msg(11), msg(12)];
    const result = mergeRealtimePage(current, [
      msg(1),
      msg(2),
      { ...firstLoaded },
      msg(13),
    ]);

    expect(result.map((m) => m.id)).toEqual(["10", "11", "12", "13"]);
    expect(result[0]).toBe(firstLoaded);
  });
});
