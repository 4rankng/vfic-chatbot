import { vficConfig } from "@/lib/vfic/config";
import type { Lead, Message } from "../types";
import {
  apiJson,
  getAccessToken,
} from "../providers/rest/api";

// Chat data access over the FastAPI REST + SSE backend (replaces the Supabase
// client + postgres_changes realtime). Conversations are keyed by their UUID
// `id` (the react-admin record identity); the lead<->conversation join stays
// zalo-keyed on the inbox side (leads carry zalo_id, conversations zalo_chat_id).

type ApiRecord = Record<string, unknown>;
interface ListEnvelope {
  data: ApiRecord[];
  total: number;
}

// Map a typed backend MessageOut to the CRM's Message view model.
//   sender WORKER  -> inbound (candidate)
//   sender BOT/RECRUITER -> outbound
//   sender SYSTEM  -> system
const toMessage = (row: ApiRecord): Message => {
  const sender = String(row.sender ?? "").toUpperCase();
  const recruiterId = row.recruiter_id != null ? String(row.recruiter_id) : null;
  const type: Message["type"] =
    sender === "SYSTEM" ? "system" : sender === "WORKER" ? "inbound" : "outbound";
  return {
    id: String(row.id),
    zalo_message_id: String(row.zalo_message_id ?? row.id),
    conversation_id: String(row.conversation_id ?? ""),
    type,
    content: String(row.body ?? ""),
    data: { recruiter_id: recruiterId },
    created_at: String(row.created_at ?? new Date().toISOString()),
  };
};

export const chatRepository = {
  /**
   * Resolve the most recent lead per zalo id (inbox lead badges). The backend
   * leads list honours `zalo_ids` (csv `IN`) and orders by updated_at DESC; the
   * consumer keeps the first (newest) lead per zalo_id.
   */
  async getLeadsByZaloIds(zaloIds: string[]): Promise<Lead[]> {
    const distinct = Array.from(new Set(zaloIds.filter(Boolean)));
    if (distinct.length === 0) return [];
    const sp = new URLSearchParams({
      zalo_ids: distinct.join(","),
      per_page: String(distinct.length),
    });
    const body = await apiJson<ListEnvelope>(`/api/v1/leads?${sp.toString()}`);
    return body.data as unknown as Lead[];
  },

  /**
   * Latest message snippet per conversation, for inbox row previews. ONE batched
   * request (chunked at the backend's 200-id cap) instead of an N-fanout of
   * per-conversation GETs. The endpoint returns {conversation_id -> body}; we
   * re-key by zalo_chat_id for the inbox consumers.
   */
  async getLastMessages(
    conversations: { id: string; zalo_chat_id: string }[],
  ): Promise<Record<string, string>> {
    const out: Record<string, string> = {};
    const valid = conversations.filter((c) => c?.id && c?.zalo_chat_id);
    if (valid.length === 0) return out;
    const zaloById = new Map(valid.map((c) => [c.id, c.zalo_chat_id]));
    for (let i = 0; i < valid.length; i += 200) {
      const chunk = valid.slice(i, i + 200).map((c) => c.id);
      let snippets: Record<string, string> = {};
      try {
        const resp = await apiJson<{ snippets: Record<string, string> }>(
          `/api/v1/conversations/last-messages/batch?ids=${encodeURIComponent(chunk.join(","))}`,
        );
        snippets = resp?.snippets ?? {};
      } catch {
        snippets = {};
      }
      for (const [cid, text] of Object.entries(snippets)) {
        const zalo = zaloById.get(cid);
        if (zalo && text) out[zalo] = text;
      }
    }
    return out;
  },

  /**
   * Paginated message history for a conversation. The backend returns the
   * newest page by default, or the page older than `beforeId` (the integer id of
   * the oldest currently-visible message) for cursor-based load-more. Server
   * order is newest-first; we reverse to chronological for the virtualised
   * scroller. A full page (== limit) implies more history may exist.
   */
  async getConversationMessages(
    conversationId: string,
    options?: { limit?: number; beforeId?: string },
  ): Promise<{ messages: Message[]; hasMore: boolean }> {
    const limit = options?.limit ?? 10;
    const sp = new URLSearchParams({ per_page: String(limit) });
    if (options?.beforeId) {
      sp.set("before_id", String(options.beforeId));
    }
    const body = await apiJson<ListEnvelope>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages?${sp.toString()}`,
    );
    const mapped = (body.data ?? []).map(toMessage);
    mapped.reverse();
    return { messages: mapped, hasMore: mapped.length >= limit };
  },

  /**
   * Approximate total message count for a contact's Zalo thread (lead timeline
   * activity signal). Resolves the conversation by zalo_chat_id, then reads the
   * messages page total (capped at the per_page ceiling).
   */
  async getMessageCount(zaloChatId: string): Promise<number> {
    if (!zaloChatId) return 0;
    const convSp = new URLSearchParams({ zalo_chat_id: zaloChatId, per_page: "1" });
    const conv = await apiJson<ListEnvelope>(
      `/api/v1/conversations?${convSp.toString()}`,
    );
    const convId = conv.data?.[0]?.id;
    if (!convId) return 0;
    const msgSp = new URLSearchParams({ per_page: "200" });
    const msgs = await apiJson<ListEnvelope>(
      `/api/v1/conversations/${encodeURIComponent(String(convId))}/messages?${msgSp.toString()}`,
    );
    return msgs.total ?? msgs.data.length;
  },

  /**
   * Subscribe to new messages for a conversation over the SSE realtime stream.
   * EventSource cannot set headers, so the access JWT rides in `?token=`. The
   * stream is global (one channel); we filter `message.created` events by
   * `conversation_id`. The event payload carries only ids, so on a match we
   * refetch the latest page and merge — the consumer dedups by message id.
   * Returns an unsubscribe fn (no-op when there is no session token).
   */
  subscribeToMessages(
    conversationId: string,
    onNewMessage: (msg: Message) => void,
  ): () => void {
    const token = getAccessToken();
    if (!token || !conversationId) {
      return () => {
        /* nothing to clean up */
      };
    }
    const url = `${vficConfig.realtimeUrl}?token=${encodeURIComponent(token)}`;
    let closed = false;
    const es = new EventSource(url);

    es.addEventListener("message.created", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as {
        conversation_id?: string;
      };
      if (payload.conversation_id !== conversationId) return;
      // Refetch + merge (SSE carries ids only). Ignore failures — the next
      // event/list refresh reconciles.
      chatRepository
        .getConversationMessages(conversationId, { limit: 25 })
        .then(({ messages }) => {
          for (const m of messages) onNewMessage(m);
        })
        .catch(() => {
          /* best-effort */
        });
    });

    es.onerror = () => {
      // EventSource auto-reconnects; nothing to do here.
    };

    return () => {
      if (closed) return;
      closed = true;
      es.close();
    };
  },
};
