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
});

describe("mergeRealtimePage", () => {
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
