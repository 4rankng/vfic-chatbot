import { ApiError, apiJson } from "@/lib/apiClient";

import type {
  HumanReplyStatus,
  RetryConversationReplyPort,
  SendConversationReplyPort,
} from "../application/conversation-operations";

class HumanReplyAdapterError extends Error {
  constructor(
    public readonly status: HumanReplyStatus,
    message: string,
    public readonly httpStatus?: number,
  ) {
    super(message);
    this.name = "HumanReplyAdapterError";
  }
}

const statusFor = (httpStatus: number): HumanReplyStatus => {
  if (httpStatus === 401) return "unauthorized";
  if (httpStatus === 403) return "forbidden";
  if (httpStatus === 409) return "conflict";
  if (httpStatus === 422) return "unavailable";
  if (httpStatus >= 500) return "provider";
  return "error";
};

const mapReplyError = (error: unknown, operation: string): Error => {
  if (error instanceof ApiError) {
    return new HumanReplyAdapterError(
      statusFor(error.status),
      `${operation} returned ${error.status}`,
      error.status,
    );
  }
  return new HumanReplyAdapterError(
    "network",
    `Network error calling ${operation}`,
  );
};

export const httpHumanReplyAdapter: SendConversationReplyPort &
  RetryConversationReplyPort = {
  async sendHumanReply(conversationId, message) {
    try {
      await apiJson(
        `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`,
        { method: "POST", body: { body: message } },
      );
    } catch (error: unknown) {
      throw mapReplyError(error, "Reply endpoint");
    }
  },

  async retryHumanReply(conversationId, messageId) {
    try {
      await apiJson<void>(
        `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/retry`,
        { method: "POST" },
      );
    } catch (error: unknown) {
      throw mapReplyError(error, "Reply retry endpoint");
    }
  },
};
