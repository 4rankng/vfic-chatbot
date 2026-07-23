import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiJson } = vi.hoisted(() => ({
  apiJson: vi.fn(),
}));

vi.mock("@/lib/apiClient", () => ({
  ApiError: class ApiError extends Error {
    constructor(
      public readonly status: number,
      message: string,
    ) {
      super(message);
    }
  },
  apiJson,
}));

import { retryHumanReply, sendHumanReply } from "./humanReplyService";

describe("humanReplyService compatibility facade", () => {
  beforeEach(() => {
    apiJson.mockReset();
    apiJson.mockResolvedValue(undefined);
  });

  it("works when imported directly without composition-order side effects", async () => {
    await sendHumanReply({
      conversationId: "conversation-1",
      message: "Xin chào",
    });
    await retryHumanReply({
      conversationId: "conversation-1",
      messageId: "message-1",
    });

    expect(apiJson).toHaveBeenNthCalledWith(
      1,
      "/api/v1/conversations/conversation-1/messages",
      {
        method: "POST",
        body: { body: "Xin chào" },
      },
    );
    expect(apiJson).toHaveBeenNthCalledWith(
      2,
      "/api/v1/conversations/conversation-1/messages/message-1/retry",
      { method: "POST" },
    );
  });
});
