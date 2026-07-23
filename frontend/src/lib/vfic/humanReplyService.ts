export type HumanReplyStatus =
  | "disabled"
  | "unauthorized"
  | "forbidden"
  | "conflict"
  | "unavailable"
  | "provider"
  | "network"
  | "error";

export class HumanReplyError extends Error {
  constructor(
    public readonly status: HumanReplyStatus,
    message: string,
    public readonly httpStatus?: number,
  ) {
    super(message);
    this.name = "HumanReplyError";
  }
}

export type SendHumanReplyCommand = {
  conversationId: string;
  message: string;
};

export type RetryHumanReplyCommand = {
  conversationId: string;
  messageId: string;
};

export interface HumanReplyServicePort {
  send(command: SendHumanReplyCommand): Promise<void>;
  retry(command: RetryHumanReplyCommand): Promise<void>;
}

const statusFor = (httpStatus: number): HumanReplyStatus => {
  if (httpStatus === 401) return "unauthorized";
  if (httpStatus === 403) return "forbidden";
  if (httpStatus === 409) return "conflict";
  if (httpStatus === 422) return "unavailable";
  if (httpStatus >= 500) return "provider";
  return "error";
};

const mapReplyError = (error: unknown, operation: string): HumanReplyError => {
  if (error instanceof ApiError) {
    return new HumanReplyError(
      statusFor(error.status),
      `${operation} returned ${error.status}`,
      error.status,
    );
  }
  return new HumanReplyError("network", `Network error calling ${operation}`);
};

export const sendHumanReply = async (
  command: SendHumanReplyCommand,
): Promise<void> => {
  try {
    await apiJson(
      `/api/v1/conversations/${encodeURIComponent(command.conversationId)}/messages`,
      {
        method: "POST",
        body: { body: command.message },
      },
    );
  } catch (error: unknown) {
    throw mapReplyError(error, "Reply endpoint");
  }
};

export const retryHumanReply = async (
  command: RetryHumanReplyCommand,
): Promise<void> => {
  try {
    await apiJson<void>(
      `/api/v1/conversations/${encodeURIComponent(command.conversationId)}/messages/${encodeURIComponent(command.messageId)}/retry`,
      { method: "POST" },
    );
  } catch (error: unknown) {
    throw mapReplyError(error, "Reply retry endpoint");
  }
};
import { ApiError, apiJson } from "@/lib/apiClient";
