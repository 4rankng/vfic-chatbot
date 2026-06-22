// Human-reply bridge: SPA -> n8n human-reply webhook.
//
// SECURITY: ownership is established by the Bearer JWT (the Supabase session
// token), NOT by a body field. n8n introspects the JWT via Supabase's
// /auth/v1/user endpoint and uses the introspected user id as the SOLE
// ownership + audit source. The request body carries only the conversational
// payload — no recruiter_id — so a client cannot spoof another recruiter.
//
// Phase 3b will route this through the vfic_human_relay Edge function
// (HMAC-signed) instead of calling n8n directly; the contract here is
// unchanged.

import { vficConfig } from "./config";
import { getSupabaseClient } from "../../components/atomic-crm/providers/supabase/supabase";

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

const authHeader = async (): Promise<string> => {
  const { data } = await getSupabaseClient().auth.getSession();
  const token = data.session?.access_token;
  if (!token) {
    throw new HumanReplyError("unauthorized", "No Supabase session token");
  }
  return `Bearer ${token}`;
};

const statusFor = (httpStatus: number): HumanReplyStatus => {
  if (httpStatus === 401) return "unauthorized";
  if (httpStatus === 403) return "forbidden";
  if (httpStatus === 409) return "conflict";
  if (httpStatus >= 500) return "network";
  return "error";
};

export const sendHumanReply = async ({
  zaloChatId,
  message,
}: {
  zaloChatId: string;
  message: string;
}): Promise<void> => {
  const webhookUrl = vficConfig.humanReplyWebhookUrl;
  if (!webhookUrl) {
    throw new HumanReplyError("disabled", "Human-reply webhook not configured");
  }
  const header = await authHeader();

  let response: Response;
  try {
    response = await fetch(webhookUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: header,
      },
      // No recruiter_id: ownership comes from the introspected JWT.
      body: JSON.stringify({ zalo_chat_id: zaloChatId, message }),
    });
  } catch {
    throw new HumanReplyError("network", "Network error calling reply webhook");
  }

  if (!response.ok) {
    throw new HumanReplyError(
      statusFor(response.status),
      `Reply webhook returned ${response.status}`,
    );
  }
};
