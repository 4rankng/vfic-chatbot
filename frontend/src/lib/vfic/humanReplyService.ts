// Recruiter reply bridge: SPA -> FastAPI recruiter-reply endpoint.
//
// SECURITY: ownership is established by the Bearer JWT (the user's access
// token), NOT by a body field. The backend verifies the caller is the
// assigned recruiter (or an admin) AND that the conversation is in HUMAN mode
// before sending via Zalo (server-side OA token). The request body carries
// only the message text — no recruiter_id — so a client cannot spoof another
// recruiter. `conversationId` is the conversation UUID (react-admin record id).

import {
  ApiError,
  apiJson,
} from "../../components/atomic-crm/providers/rest/api";

export type HumanReplyStatus =
  | "disabled"
  | "unauthorized"
  | "forbidden"
  | "conflict"
  | "unavailable"
  | "provider"
  | "network"
  | "error";

/**
 * Typed error surfaced to the UI. `status` maps 1:1 to an i18n key
 * (`resources.conversations.reply.<status>`); `message` is an English
 * fallback for logs only and is not shown to users.
 */
export class HumanReplyError extends Error {
  constructor(
    public readonly status: HumanReplyStatus,
    message: string,
    /** Present for HTTP failures; absent when the request never reached the API. */
    public readonly httpStatus?: number,
  ) {
    super(message);
    this.name = "HumanReplyError";
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

export const sendHumanReply = async ({
  conversationId,
  message,
}: {
  conversationId: string;
  message: string;
}): Promise<void> => {
  try {
    await apiJson(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        body: { body: message },
      },
    );
  } catch (error: unknown) {
    if (error instanceof ApiError) {
      throw new HumanReplyError(
        statusFor(error.status),
        `Reply endpoint returned ${error.status}`,
        error.status,
      );
    }
    throw new HumanReplyError("network", "Network error calling reply endpoint");
  }
};

/**
 * Optional forward-compatible hook for the durable-delivery retry action.
 * The service intentionally treats the endpoint response as empty: the
 * authoritative message state arrives through the existing REST/realtime
 * message feed, so no speculative response contract is introduced here.
 */
export const retryHumanReply = async ({
  conversationId,
  messageId,
}: {
  conversationId: string;
  messageId: string;
}): Promise<void> => {
  try {
    await apiJson<void>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/retry`,
      { method: "POST" },
    );
  } catch (error: unknown) {
    if (error instanceof ApiError) {
      throw new HumanReplyError(
        statusFor(error.status),
        `Reply retry endpoint returned ${error.status}`,
        error.status,
      );
    }
    throw new HumanReplyError("network", "Network error calling reply retry endpoint");
  }
};
