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
} from "../../components/atomic-crm/providers/supabase/supabase";

export type HumanReplyStatus =
  | "disabled"
  | "unauthorized"
  | "forbidden"
  | "conflict"
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
  ) {
    super(message);
    this.name = "HumanReplyError";
  }
}

const statusFor = (httpStatus: number): HumanReplyStatus => {
  if (httpStatus === 401) return "unauthorized";
  if (httpStatus === 403) return "forbidden";
  if (httpStatus === 409) return "conflict";
  if (httpStatus >= 500) return "network";
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
      );
    }
    throw new HumanReplyError("network", "Network error calling reply endpoint");
  }
};
