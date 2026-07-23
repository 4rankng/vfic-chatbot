import { describe, expect, it } from "vitest";

import type { Conversation } from "../../types";
import { deriveConversationModeState } from "./conversation-mode";

const conversation = (overrides: Partial<Conversation> = {}): Conversation =>
  ({
    id: "conversation-1",
    mode: "bot",
    assigned_recruiter_id: null,
    created_at: "2026-07-16T10:00:00.000Z",
    updated_at: "2026-07-16T12:00:00.000Z",
    ...overrides,
  }) as Conversation;

describe("deriveConversationModeState", () => {
  it("requires claim for an unassigned human conversation", () => {
    expect(
      deriveConversationModeState({
        record: conversation({ mode: "human" }),
        locallyClaimed: false,
      }),
    ).toEqual({
      effectiveMode: "human",
      isBotMode: false,
      needsClaim: true,
      canHumanReply: false,
    });
  });

  it("unlocks reply after a local human claim", () => {
    expect(
      deriveConversationModeState({
        record: conversation({ mode: "human" }),
        locallyClaimed: true,
      }),
    ).toEqual({
      effectiveMode: "human",
      isBotMode: false,
      needsClaim: false,
      canHumanReply: true,
    });
  });

  it("treats semi-auto as human-reply capable", () => {
    expect(
      deriveConversationModeState({
        record: conversation({ mode: "semi_auto" }),
        locallyClaimed: false,
      }),
    ).toEqual({
      effectiveMode: "semi_auto",
      isBotMode: false,
      needsClaim: false,
      canHumanReply: true,
    });
  });
});
