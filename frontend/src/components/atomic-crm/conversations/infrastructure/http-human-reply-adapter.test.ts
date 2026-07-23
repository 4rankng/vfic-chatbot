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

import { ApiError } from "@/lib/apiClient";
import { isHumanReplyFailure } from "../application/conversation-operations";
import { httpHumanReplyAdapter } from "./http-human-reply-adapter";

describe("httpHumanReplyAdapter", () => {
  beforeEach(() => {
    apiJson.mockReset();
    apiJson.mockResolvedValue(undefined);
  });

  it("maps send and retry operations to the conversation API", async () => {
    await httpHumanReplyAdapter.sendHumanReply(
      "conversation/1",
      "Xin chào",
    );
    await httpHumanReplyAdapter.retryHumanReply(
      "conversation/1",
      "message/1",
    );

    expect(apiJson).toHaveBeenNthCalledWith(
      1,
      "/api/v1/conversations/conversation%2F1/messages",
      {
        method: "POST",
        body: { body: "Xin chào" },
      },
    );
    expect(apiJson).toHaveBeenNthCalledWith(
      2,
      "/api/v1/conversations/conversation%2F1/messages/message%2F1/retry",
      { method: "POST" },
    );
  });

  it("translates HTTP and network failures into application statuses", async () => {
    apiJson
      .mockRejectedValueOnce(new ApiError(409, "conflict"))
      .mockRejectedValueOnce(new TypeError("offline"));

    const conflict = await httpHumanReplyAdapter
      .sendHumanReply("conversation-1", "hello")
      .catch((error: unknown) => error);
    const network = await httpHumanReplyAdapter
      .retryHumanReply("conversation-1", "message-1")
      .catch((error: unknown) => error);

    expect(isHumanReplyFailure(conflict)).toBe(true);
    expect(conflict).toMatchObject({ status: "conflict", httpStatus: 409 });
    expect(isHumanReplyFailure(network)).toBe(true);
    expect(network).toMatchObject({ status: "network" });
  });
});
