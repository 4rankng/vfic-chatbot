export type ConversationMessage = {
  id: string;
  zalo_message_id?: string | null;
  conversation_id: string;
  type: "inbound" | "outbound" | "system";
  content: string;
  delivery_status?:
    | "pending"
    | "sending"
    | "sent"
    | "failed"
    | "send_unknown"
    | "suppressed";
  delivery_attempts?: number;
  external_error?: string | null;
  data: { recruiter_id?: string | null } | null;
  created_at: string;
};
