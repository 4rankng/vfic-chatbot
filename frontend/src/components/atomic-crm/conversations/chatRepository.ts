import { getSupabaseClient } from "../providers/supabase/supabase";
import type { Lead, Message } from "../types";

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

// PostgREST URL-length safety: fetch leads in bounded batches and merge.
const LEAD_BATCH_SIZE = 100;

export const chatRepository = {
  /**
   * Fetch leads for many zalo ids in parallel batches (URL-safe chunking),
   * replacing the old per-conversation N+1 lookup. Returns the most recent
   * lead per zalo_id (matches the previous `data?.[0]` + updated_at DESC rule).
   */
  async getLeadsByZaloIds(zaloIds: string[]): Promise<Lead[]> {
    const distinct = Array.from(new Set(zaloIds.filter(Boolean)));
    if (distinct.length === 0) return [];

    const chunks: string[][] = [];
    for (let i = 0; i < distinct.length; i += LEAD_BATCH_SIZE) {
      chunks.push(distinct.slice(i, i + LEAD_BATCH_SIZE));
    }
    // Fire every chunk concurrently. Promise.all preserves chunk order, so the
    // consumer's "first lead per zalo_id wins" dedup still sees updated_at DESC.
    // The Supabase client resolves (data/error) rather than rejecting.
    const responses = await Promise.all(
      chunks.map((chunk) =>
        getSupabaseClient()
          .from("leads")
          .select("*")
          .in("zalo_id", chunk)
          .order("updated_at", { ascending: false }),
      ),
    );
    const results: Lead[] = [];
    for (const { data, error } of responses) {
      if (error) throw error;
      if (data) results.push(...(data as Lead[]));
    }
    return results;
  },

  /**
   * Batched "latest message per conversation" peek — a single RPC
   * (vfic_last_messages, DISTINCT ON session_id ... id DESC) instead of the old
   * per-conversation N+1 probe. Returns a map of zalo_chat_id -> snippet text,
   * used for inbox row previews.
   */
  async getLastMessages(
    zaloIds: string[],
  ): Promise<Record<string, string>> {
    const distinct = Array.from(new Set(zaloIds.filter(Boolean)));
    if (distinct.length === 0) return {};

    const { data, error } = await getSupabaseClient().rpc(
      "vfic_last_messages",
      { p_session_ids: distinct },
    );
    if (error) throw error;

    const out: Record<string, string> = {};
    for (const row of (data as Array<{ id: number; session_id: string; message: unknown }>) ?? []) {
      // Reuse toMessage so direction + content extraction stay in one place.
      const text = toMessage(row)?.content ?? "";
      if (text && row.session_id && !(row.session_id in out)) {
        out[row.session_id] = text;
      }
    }
    return out;
  },

  async getConversationMessages(
    zaloChatId: string,
    options?: { limit?: number; beforeId?: string },
  ): Promise<{ messages: Message[]; hasMore: boolean }> {
    let query = getSupabaseClient()
      .from("vfic_chat_histories")
      .select("*")
      .eq("session_id", zaloChatId)
      .order("id", { ascending: false });

    if (options?.beforeId) {
      query = query.lt("id", options.beforeId);
    }

    if (options?.limit) {
      query = query.limit(options.limit);
    }

    const { data, error } = await query;

    if (error) {
      throw error;
    }

    const rawCount = data?.length ?? 0;
    const limit = options?.limit ?? 10;
    const hasMore = rawCount === limit;

    const mapped = (data ?? [])
      .map(toMessage)
      .filter((m): m is Message => m != null);
    return {
      messages: mapped.reverse(),
      hasMore,
    };
  },

  /**
   * Lightweight message count for a conversation (head-only count query). Used
   * by the lead timeline's total-message-count signal.
   */
  async getMessageCount(zaloChatId: string): Promise<number> {
    const { count, error } = await getSupabaseClient()
      .from("vfic_chat_histories")
      .select("*", { count: "exact", head: true })
      .eq("session_id", zaloChatId);
    if (error) throw error;
    return count ?? 0;
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
