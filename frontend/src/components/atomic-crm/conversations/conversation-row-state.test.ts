import { describe, expect, it } from "vitest";

import type { Conversation } from "../types";
import {
  botHasNotReplied,
  compareConversationRows,
  getConversationAttentionLabel,
  getConversationUnreadCount,
  isHumanManagedConversation,
} from "./domain/conversation-row-state";

const conversation = (overrides: Partial<Conversation>): Conversation => ({
  id: "conversation-1",
  zalo_chat_id: "zalo-1",
  mode: "bot",
  last_inbound_at: "2026-07-16T12:00:00.000Z",
  last_outbound_at: "2026-07-16T11:00:00.000Z",
  assigned_recruiter_id: null,
  created_at: "2026-07-16T10:00:00.000Z",
  updated_at: "2026-07-16T12:00:00.000Z",
  ...overrides,
});

describe("conversation row state", () => {
  it("keeps unread counters on human-managed conversations", () => {
    expect(isHumanManagedConversation(conversation({ mode: "human" }))).toBe(
      true,
    );
    expect(
      isHumanManagedConversation(conversation({ mode: "semi_auto" })),
    ).toBe(true);
    expect(isHumanManagedConversation(conversation({ mode: "bot" }))).toBe(
      false,
    );
    expect(
      getConversationUnreadCount(
        conversation({ mode: "human", unread_count: 2 }),
        new Set(),
      ),
    ).toBe(2);
    expect(
      getConversationUnreadCount(
        conversation({ mode: "bot", unread_count: 2 }),
        new Set(),
      ),
    ).toBe(0);
  });

  it("labels a bot conversation whose latest inbound message has no reply", () => {
    const pendingBotConversation = conversation({ mode: "bot" });

    expect(botHasNotReplied(pendingBotConversation)).toBe(true);
    expect(getConversationAttentionLabel(pendingBotConversation)).toBe(
      "Bot chưa phản hồi",
    );
  });

  it("does not flag a bot conversation once an outbound message follows", () => {
    const answeredBotConversation = conversation({
      mode: "bot",
      last_outbound_at: "2026-07-16T12:01:00.000Z",
    });

    expect(botHasNotReplied(answeredBotConversation)).toBe(false);
    expect(getConversationAttentionLabel(answeredBotConversation)).toBe("");
  });

  it("orders by mode, attention, unread count, then recency", () => {
    const rows = [
      conversation({
        id: "bot",
        mode: "bot",
        unread_count: 9,
      }),
      conversation({
        id: "human-read",
        mode: "human",
        unread_count: 8,
        last_outbound_at: "2026-07-16T12:01:00.000Z",
      }),
      conversation({
        id: "human-attention",
        mode: "human",
        unread_count: 1,
      }),
      conversation({
        id: "human-unread",
        mode: "human",
        unread_count: 3,
        last_outbound_at: "2026-07-16T12:01:00.000Z",
      }),
    ];

    expect(
      rows
        .sort((first, second) =>
          compareConversationRows(first, second, new Set(["human-read"])),
        )
        .map((row) => row.id),
    ).toEqual(["human-attention", "human-unread", "human-read", "bot"]);
  });

  it("orders same-attention rows by latest message, not a drifted updated_at", () => {
    // Batch maintenance can touch updated_at without a new message, so the
    // inbox must order by the timestamp each row displays (last_inbound_at).
    const rows = [
      conversation({
        id: "recently-touched",
        mode: "bot",
        last_inbound_at: "2026-07-16T09:00:00.000Z",
        last_outbound_at: null,
        updated_at: "2026-07-16T12:00:00.000Z",
      }),
      conversation({
        id: "latest-message",
        mode: "bot",
        last_inbound_at: "2026-07-16T11:00:00.000Z",
        last_outbound_at: null,
        updated_at: "2026-07-16T10:00:00.000Z",
      }),
    ];

    expect(
      rows
        .sort((first, second) => compareConversationRows(first, second, new Set()))
        .map((row) => row.id),
    ).toEqual(["latest-message", "recently-touched"]);
  });
});
