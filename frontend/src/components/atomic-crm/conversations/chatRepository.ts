import { getSupabaseClient } from "../providers/supabase/supabase";
import type { Message } from "../types";

export const extractText = (value: unknown): string => {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .map((part) =>
        part && typeof part === "object" && "text" in part
          ? String((part as { text: unknown }).text ?? "")
          : String(part),
      )
      .join("")
      .trim();
  }
  return String(value);
};

export const toMessage = (row: any): Message | null => {
  const msg = row?.message ?? {};
  const type = String(msg.type ?? "").toLowerCase();
  // ai = bot outbound; human = candidate-inbound OR recruiter-outbound;
  if (type !== "ai" && type !== "human") return null;
  const recruiterId = msg.data?.recruiter_id;
  const isRecruiter = type === "human" && Boolean(recruiterId);
  const rawContent = isRecruiter
    ? (msg.data?.content ?? msg.content)
    : msg.content;
  const content = extractText(rawContent);
  // Filter out internal agent tool calling logs
  if (
    type === "ai" &&
    content.startsWith("Calling ") &&
    content.includes("with input:")
  ) {
    return null;
  }
  const messageType: Message["type"] =
    type === "ai" || isRecruiter ? "outbound" : "inbound";
  return {
    id: String(row.id),
    zalo_message_id: String(row.id),
    conversation_id: row.session_id,
    type: messageType,
    content: content,
    data: { recruiter_id: recruiterId },
    created_at:
      msg.data?.created_at ?? row.created_at ?? new Date().toISOString(),
  };
};

export const chatRepository = {
  async getLastMessage(zaloChatId: string): Promise<Message | null> {
    const { data } = await getSupabaseClient()
      .from("vfic_chat_histories")
      .select("*")
      .eq("session_id", zaloChatId)
      .order("id", { ascending: false })
      .limit(1);

    if (data && data.length > 0) {
      return toMessage(data[0]);
    }
    return null;
  },

  async getConversationMessages(zaloChatId: string): Promise<Message[]> {
    const { data, error } = await getSupabaseClient()
      .from("vfic_chat_histories")
      .select("*")
      .eq("session_id", zaloChatId)
      .order("id", { ascending: true });

    if (error) {
      throw error;
    }

    return (data ?? []).map(toMessage).filter((m): m is Message => m != null);
  },

  subscribeToMessages(
    zaloChatId: string,
    onNewMessage: (msg: Message) => void,
  ) {
    const channel = getSupabaseClient()
      .channel(`chat_${zaloChatId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "vfic_chat_histories",
          filter: `session_id=eq.${zaloChatId}`,
        },
        (payload) => {
          const newMsg = toMessage(payload.new);
          if (newMsg) {
            onNewMessage(newMsg);
          }
        },
      )
      .subscribe();

    return () => {
      getSupabaseClient().removeChannel(channel);
    };
  },
};
