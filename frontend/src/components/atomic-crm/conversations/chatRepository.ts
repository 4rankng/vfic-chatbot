import { getRealtimeSocket } from "@/lib/vfic/realtimeSocket";
import type { Lead, Message } from "../types";
import { apiJson, getAccessToken } from "../providers/rest/api";

// Chat data access over the FastAPI REST + SSE backend (replaces the Supabase
// client + postgres_changes realtime). Conversations are keyed by their UUID
// `id` (the react-admin record identity); the lead<->conversation join stays
// zalo-keyed on the inbox side (leads carry zalo_id, conversations zalo_chat_id).

type ApiRecord = Record<string, unknown>;
interface ListEnvelope {
  data: ApiRecord[];
  total: number;
}
interface MessageCreatedPayload {
  conversation_id?: string;
  message_id?: string | number;
  message?: ApiRecord;
}

const INBOUND_SENDERS = new Set([
  "WORKER",
  "CANDIDATE",
  "USER",
  "LEAD",
  "APPLICANT",
]);
const OUTBOUND_SENDERS = new Set([
  "BOT",
  "RECRUITER",
  "ADMIN",
  "AGENT",
  "HUMAN",
]);

// Map a typed backend MessageOut to the CRM's Message view model.
//   sender WORKER/CANDIDATE/USER/LEAD/APPLICANT -> inbound (candidate)
//   sender BOT/RECRUITER/ADMIN/AGENT/HUMAN      -> outbound
//   sender SYSTEM                               -> system
const toMessage = (row: ApiRecord): Message => {
  const sender = String(row.sender ?? "").toUpperCase();
  const direction = String(row.direction ?? row.type ?? "").toLowerCase();
  const recruiterId =
    row.recruiter_id != null ? String(row.recruiter_id) : null;
  const type: Message["type"] =
    sender === "SYSTEM" || direction === "system"
      ? "system"
      : INBOUND_SENDERS.has(sender) || direction === "inbound"
        ? "inbound"
        : OUTBOUND_SENDERS.has(sender) || direction === "outbound"
          ? "outbound"
          : recruiterId
            ? "outbound"
            : "inbound";
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
   * the oldest currently-loaded message) for cursor-based load-more. Server
   * order is chronological (oldest -> newest) for the virtualised scroller.
   * A full page (== limit) implies more history may exist.
   */
  async getConversationMessages(
    conversationId: string,
    options?: { limit?: number; beforeId?: string },
  ): Promise<{ messages: Message[]; hasMore: boolean }> {
    const limit = options?.limit ?? 10;
    const sp = new URLSearchParams({ limit: String(limit) });
    if (options?.beforeId) {
      sp.set("before", String(options.beforeId));
    }
    const body = await apiJson<ListEnvelope>(
      `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages?${sp.toString()}`,
    );
    const mapped = (body.data ?? []).map(toMessage);
    return { messages: mapped, hasMore: mapped.length >= limit };
  },

  /**
   * Approximate total message count for a contact's Zalo thread (lead timeline
   * activity signal). Resolves the conversation by zalo_chat_id, then reads the
   * messages page total (capped at the per_page ceiling).
   */
  async getMessageCount(zaloChatId: string): Promise<number> {
    if (!zaloChatId) return 0;
    const convSp = new URLSearchParams({
      zalo_chat_id: zaloChatId,
      per_page: "1",
    });
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
   * Subscribe to new messages for a conversation over the Socket.IO realtime
   * transport (per-conversation rooms replace the SSE firehose). The access
   * JWT rides in the socket `auth` handshake, verified server-side on connect.
   * Joining the `conv:<id>` room scopes delivery to this conversation; modern
   * `message.created` payloads include the serialized message so the consumer
   * can append/update without a page refetch. Older id-only payloads still
   * trigger a debounced latest-page fetch as a compatibility fallback.
   * Returns an unsubscribe fn (no-op when there is no session token or
   * conversation id) which leaves the room and detaches the handler.
   */
  subscribeToMessages(
    conversationId: string,
    onNewMessages: (messages: Message[]) => void,
  ): () => void {
    if (!conversationId || !getAccessToken()) {
      return () => {
        /* nothing to clean up */
      };
    }
    const socket = getRealtimeSocket();
    let refreshTimer: number | undefined;
    let refreshInFlight = false;
    let refreshPending = false;
    let closed = false;

    const refreshLatest = () => {
      if (closed) return;
      if (refreshInFlight) {
        refreshPending = true;
        return;
      }
      refreshInFlight = true;
      chatRepository
        .getConversationMessages(conversationId, { limit: 25 })
        .then(({ messages }) => {
          if (closed) return;
          onNewMessages(messages);
        })
        .catch(() => {
          /* best-effort */
        })
        .finally(() => {
          refreshInFlight = false;
          if (!closed && refreshPending) {
            refreshPending = false;
            refreshLatest();
          }
        });
    };

    const handler = (payload: MessageCreatedPayload | undefined) => {
      if (closed) return;
      // The server emits to conv:<id>, but the socket may be in several rooms,
      // so keep a defensive conversation_id check (parity with the SSE path).
      const payloadConversationId =
        payload?.conversation_id ??
        (payload?.message
          ? String(payload.message.conversation_id ?? "")
          : undefined);
      if (payloadConversationId !== conversationId) return;

      if (payload?.message) {
        onNewMessages([toMessage(payload.message)]);
        return;
      }

      // Legacy id-only event: refetch + merge. Ignore failures — the next
      // event / list refresh reconciles.
      window.clearTimeout(refreshTimer);
      refreshTimer = window.setTimeout(refreshLatest, 80);
    };

    socket.on("message.created", handler);
    // Connect lazily (autoConnect is false). Emits made before connect are
    // buffered and flushed once the server accepts the auth handshake.
    if (!socket.connected) {
      socket.connect();
    }
    socket.emit("join conversation", { conversation_id: conversationId });

    return () => {
      if (closed) return;
      closed = true;
      window.clearTimeout(refreshTimer);
      socket.off("message.created", handler);
      socket.emit("leave conversation", { conversation_id: conversationId });
    };
  },
};
