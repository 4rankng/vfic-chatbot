import {
  type DataProvider,
  type CreateParams,
  type CreateResult,
  type DeleteManyParams,
  type DeleteManyResult,
  type DeleteParams,
  type DeleteResult,
  type GetListParams,
  type GetListResult,
  type GetManyParams,
  type GetManyReferenceParams,
  type GetManyReferenceResult,
  type GetManyResult,
  type GetOneParams,
  type GetOneResult,
  type Identifier,
  type RaRecord,
  type UpdateManyParams,
  type UpdateManyResult,
  type UpdateParams,
  type UpdateResult,
} from "ra-core";
import { apiJson, ApiError } from "@/lib/apiClient";
import type { ConversationModeWriter } from "../../conversations/application/conversation-actions";
import type {
  MarkConversationReadPort,
  RetryConversationReplyPort,
  SendConversationReplyPort,
} from "../../conversations/application/conversation-operations";
import type { EditableConversationMode } from "../../conversations/domain/conversation-mode";
import { httpHumanReplyAdapter } from "../../conversations/infrastructure/http-human-reply-adapter";

// REST dataProvider (replaces ra-supabase-core / PostgREST).
//
// Standard react-admin verbs map onto /api/v1/{resource} with the backend's
// `{ data, total }` list envelope. The backend is keyed on each resource's
// natural id (UUID for conversations/users, int for leads/jobs), so the
// users->profiles alias is gone. VFIC-specific custom methods (takeover,
// release, mark-as-read, recruiter reply, user provisioning) target the
// dedicated action routes and are re-keyed on the conversation UUID id (the
// react-admin record identity), not the legacy zalo_chat_id.

const BASE = "/api/v1";

// Some CRM resources keep their legacy react-admin name but target a backend
// route whose path differs (the name is unchanged so existing List/Show
// registrations and <Resource name=...> still resolve). Map resource -> backend
// path segment here.
const RESOURCE_PATH: Record<string, string> = {
  knowledge_sources: "knowledge/documents",
  projects: "knowledge/projects",
  knowledge_bases: "knowledge-bases",
};

const pathFor = (resource: string): string =>
  `${BASE}/${RESOURCE_PATH[resource] ?? resource}`;
const onePath = (resource: string, id: Identifier): string =>
  `${pathFor(resource)}/${encodeURIComponent(String(id))}`;

// A backend JSON row. react-admin records always carry an `id`; every other
// field is resource-specific and untyped on the wire.
type ApiRecord = Record<string, unknown> & { id: Identifier };
interface ListEnvelope {
  data: ApiRecord[];
  total: number;
}

// Backend enums are uppercase; the CRM render layer reads lowercase mode values
// (`=== "bot"` / `=== "human"`). Normalise conversation records so those checks
// still hold. CLOSED maps to "closed" (falls through bot/human branches). The
// record's own shape is preserved — this is a field normaliser, not a mapper.
const normalize = <RecordType extends ApiRecord>(
  resource: string,
  record: RecordType,
): RecordType => {
  if (resource === "conversations" && typeof record.mode === "string") {
    return { ...record, mode: record.mode.toLowerCase() };
  }
  return record;
};

// Marshals backend JSON into a react-admin record. The wire format is untyped
// JSON, so `toRec` is the single place where a parsed row is asserted into the
// record type its caller asked for; every verb below stays typed around it.
const toRec = <RecordType extends RaRecord>(
  resource: string,
  record: ApiRecord,
): RecordType => normalize(resource, record) as RecordType;

const buildListQuery = (
  params: GetListParams | GetManyReferenceParams,
  resource?: string,
): string => {
  const sp = new URLSearchParams();
  const pagination = params.pagination ?? { page: 1, perPage: 25 };
  sp.set("page", String(pagination.page ?? 1));
  sp.set("per_page", String(pagination.perPage ?? 25));

  const sort = params.sort;
  if (sort?.field && sort.field !== "id") {
    sp.set("sort", sort.field);
    sp.set("order", (sort.order ?? "DESC").toUpperCase());
  }

  const filter = (params.filter ?? {}) as Record<string, unknown>;
  for (const [key, value] of Object.entries(filter)) {
    if (value === undefined || value === null || value === "") continue;
    // ra filter keys pass straight through as query params; the backend honours
    // the ones it knows (mode/status/zalo_chat_id/needs_attention on
    // conversations; stage/needs_reply/zalo_id/zalo_ids on leads) and ignores
    // the rest.
    const wireValue =
      resource === "conversations" && (key === "mode" || key === "status")
        ? String(value).toUpperCase()
        : Array.isArray(value)
          ? value.join(",")
          : String(value);
    sp.set(key, wireValue);
  }
  return sp.toString();
};

// Every verb mirrors react-admin's own generic signature so callers keep
// `RecordType` inference and the provider is checked against `DataProvider`.
const restProvider = {
  async getList<RecordType extends RaRecord = RaRecord>(
    resource: string,
    params: GetListParams,
  ): Promise<GetListResult<RecordType>> {
    const body = await apiJson<ListEnvelope>(
      `${pathFor(resource)}?${buildListQuery(params, resource)}`,
    );
    return {
      data: body.data.map((r) => toRec<RecordType>(resource, r)),
      total: body.total,
    };
  },

  async getOne<RecordType extends RaRecord = RaRecord>(
    resource: string,
    params: GetOneParams,
  ): Promise<GetOneResult<RecordType>> {
    const record = await apiJson<ApiRecord>(onePath(resource, params.id));
    return { data: toRec<RecordType>(resource, record) };
  },

  async getMany<RecordType extends RaRecord = RaRecord>(
    resource: string,
    params: GetManyParams,
  ): Promise<GetManyResult<RecordType>> {
    // No batch-by-id endpoint; fan out getOne per id (bounded N, small).
    const rows = await Promise.all(
      params.ids.map((id) =>
        apiJson<ApiRecord>(onePath(resource, id)).catch(() => null),
      ),
    );
    return {
      data: rows
        .filter((r): r is ApiRecord => r !== null)
        .map((r) => toRec<RecordType>(resource, r)),
    };
  },

  async getManyReference<RecordType extends RaRecord = RaRecord>(
    resource: string,
    params: GetManyReferenceParams,
  ): Promise<GetManyReferenceResult<RecordType>> {
    // ReferenceManyField filters by { [target]: id }; fold it into the filter.
    const merged: GetManyReferenceParams = {
      ...params,
      filter: { ...params.filter, [params.target]: params.id },
    };
    const body = await apiJson<ListEnvelope>(
      `${pathFor(resource)}?${buildListQuery(merged, resource)}`,
    );
    return {
      data: body.data.map((r) => toRec<RecordType>(resource, r)),
      total: body.total,
    };
  },

  async create<
    RecordType extends Omit<RaRecord, "id"> = Omit<RaRecord, "id">,
    ResultRecordType extends RaRecord = RecordType & { id: Identifier },
  >(
    resource: string,
    params: CreateParams<RecordType>,
  ): Promise<CreateResult<ResultRecordType>> {
    const record = await apiJson<ApiRecord>(pathFor(resource), {
      method: "POST",
      body: params.data,
    });
    return { data: toRec<ResultRecordType>(resource, record) };
  },

  async update<RecordType extends RaRecord = RaRecord>(
    resource: string,
    params: UpdateParams<RecordType>,
  ): Promise<UpdateResult<RecordType>> {
    const record = await apiJson<ApiRecord>(onePath(resource, params.id), {
      method: "PATCH",
      body: params.data,
    });
    return { data: toRec<RecordType>(resource, record) };
  },

  async updateMany<RecordType extends RaRecord = RaRecord>(
    resource: string,
    params: UpdateManyParams,
  ): Promise<UpdateManyResult<RecordType>> {
    const ids = await Promise.all(
      params.ids.map((id) =>
        apiJson<ApiRecord>(onePath(resource, id), {
          method: "PATCH",
          body: params.data,
        })
          .then(() => id)
          .catch(() => null),
      ),
    );
    return { data: ids.filter((id): id is RecordType["id"] => id !== null) };
  },

  async delete<RecordType extends RaRecord = RaRecord>(
    resource: string,
    params: DeleteParams<RecordType>,
  ): Promise<DeleteResult<RecordType>> {
    await apiJson<void>(onePath(resource, params.id), { method: "DELETE" });
    // react-admin ignores this payload; the deleted record when the caller
    // passed it, and otherwise a record carrying just the id.
    return {
      data:
        params.previousData ?? toRec<RecordType>(resource, { id: params.id }),
    };
  },

  async deleteMany<RecordType extends RaRecord = RaRecord>(
    resource: string,
    params: DeleteManyParams<RecordType>,
  ): Promise<DeleteManyResult<RecordType>> {
    await Promise.all(
      params.ids.map((id) =>
        apiJson<void>(onePath(resource, id), { method: "DELETE" }).catch(
          () => null,
        ),
      ),
    );
    return { data: params.ids };
  },
} satisfies DataProvider;

// The VFIC-specific surface of the provider — conversation mutations and admin
// user provisioning — which react-admin's own verbs don't cover. Declared
// explicitly so the contract is readable here instead of being inferred from
// the factory's object literal.
export interface CrmDataProviderMethods {
  /** Recruiter reply. Ownership is established by the Bearer JWT, not a body id. */
  sendHumanReply(conversationId: string, message: string): Promise<void>;
  retryHumanReply(conversationId: string, messageId: string): Promise<void>;
  takeOverConversation(conversationId: string): Promise<ApiRecord>;
  releaseConversation(conversationId: string): Promise<ApiRecord>;
  /** Nudge the bot to answer the latest unanswered candidate message now. */
  forceBotReply(conversationId: string): Promise<ApiRecord>;
  /** Ask the bot to read the conversation and answer only if it should. */
  botReply(conversationId: string): Promise<ApiRecord>;
  setConversationMode(
    conversationId: string,
    mode: EditableConversationMode,
  ): Promise<ApiRecord>;
  clearConversationHistory(conversationId: string): Promise<void>;
  markAsRead(conversationId: string): Promise<ApiRecord>;
  createProfile(body: Record<string, unknown>): Promise<ApiRecord>;
  disableUser(userId: string): Promise<ApiRecord>;
  enableUser(userId: string): Promise<ApiRecord>;
  resetUserPassword(userId: string, body: { password: string }): Promise<void>;
  /** Sign-up is disabled; accounts are provisioned by an admin. */
  signUp(body: {
    email: string;
    password: string;
    first_name: string;
    last_name: string;
  }): Promise<{ user: null; session: null }>;
}

/**
 * The type every consumer is typed against: react-admin's verbs, the
 * VFIC-specific methods above, and the conversation ports the inbox dispatches
 * through. Intersecting the ports keeps provider and port in lockstep — a
 * rename or removal on either side breaks the build instead of a call site.
 */
export type CrmDataProvider = DataProvider &
  CrmDataProviderMethods &
  ConversationModeWriter &
  MarkConversationReadPort &
  SendConversationReplyPort &
  RetryConversationReplyPort;

const getDataProviderWithCustomMethods = (): CrmDataProvider => ({
  ...restProvider,

  // Recruiter reply: ownership is established by the Bearer JWT (the backend
  // verifies the caller owns the conversation and mode=HUMAN). The body carries
  // only the message text — no recruiter_id — closing the spoof vector.
  // `conversationId` is the conversation UUID (react-admin record id).
  async sendHumanReply(conversationId: string, message: string) {
    await httpHumanReplyAdapter.sendHumanReply(conversationId, message);
  },

  async retryHumanReply(conversationId: string, messageId: string) {
    await httpHumanReplyAdapter.retryHumanReply(conversationId, messageId);
  },

  async takeOverConversation(conversationId: string) {
    return apiJson<ApiRecord>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/take-over`,
      { method: "POST" },
    ).then((r) => normalize("conversations", r));
  },

  async releaseConversation(conversationId: string) {
    return apiJson<ApiRecord>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/release`,
      { method: "POST" },
    ).then((r) => normalize("conversations", r));
  },

  async forceBotReply(conversationId: string) {
    return apiJson<ApiRecord>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/force-bot-reply`,
      { method: "POST" },
    ).then((r) => normalize("conversations", r));
  },

  async botReply(conversationId: string) {
    return apiJson<ApiRecord>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/bot-reply`,
      { method: "POST" },
    ).then((r) => normalize("conversations", r));
  },

  async setConversationMode(
    conversationId: string,
    mode: EditableConversationMode,
  ) {
    const action =
      mode === "human"
        ? "take-over"
        : mode === "semi_auto"
          ? "semi-auto"
          : "release";
    return apiJson<ApiRecord>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/${action}`,
      { method: "POST" },
    ).then((r) => normalize("conversations", r));
  },

  // Admin: hard-delete all messages + bot_runs for a conversation (204).
  async clearConversationHistory(conversationId: string) {
    await apiJson<void>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/history`,
      { method: "DELETE" },
    );
  },

  // Reset unread_count to 0. Returns the updated conversation (callers refresh).
  async markAsRead(conversationId: string) {
    return apiJson<ApiRecord>(
      `${BASE}/conversations/${encodeURIComponent(conversationId)}/read`,
      { method: "POST" },
    ).then((r) => normalize("conversations", r));
  },

  // Admin user provisioning (replaces the vfic_create_user edge function).
  async createProfile(body: Record<string, unknown>) {
    return apiJson<ApiRecord>(`${BASE}/users`, { method: "POST", body });
  },

  async disableUser(userId: string) {
    return apiJson<ApiRecord>(
      `${BASE}/users/${encodeURIComponent(userId)}/disable`,
      {
        method: "POST",
      },
    );
  },

  async enableUser(userId: string) {
    return apiJson<ApiRecord>(
      `${BASE}/users/${encodeURIComponent(userId)}/enable`,
      {
        method: "POST",
      },
    );
  },

  async resetUserPassword(userId: string, body: { password: string }) {
    return apiJson<void>(
      `${BASE}/users/${encodeURIComponent(userId)}/reset-password`,
      {
        method: "POST",
        body,
      },
    );
  },

  // Sign-up is disabled. VFIC accounts are provisioned out-of-band by an admin.
  async signUp(_body: {
    email: string;
    password: string;
    first_name: string;
    last_name: string;
  }): Promise<{ user: null; session: null }> {
    throw new ApiError(403, "Sign-up is disabled.");
  },
});

export const getDataProvider = (): CrmDataProvider =>
  getDataProviderWithCustomMethods();
